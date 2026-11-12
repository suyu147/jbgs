"""AI 模拟面试：DeepSeek 生成问题/点评/报告 + 国内 ASR 语音转写。

DeepSeek 未配置时自动降级为基于岗位技能的模板问题，保证功能可演示；
ASR 未配置时语音端点返回明确错误，用户仍可打字作答。
"""

import json
import re

import httpx

from .config import settings


class InterviewProviderError(RuntimeError):
    """面试 LLM 或 ASR 供应商调用失败。"""


def interview_llm_configured() -> bool:
    return bool(settings.deepseek_api_key.strip())


def asr_configured() -> bool:
    return bool(settings.interview_asr_api_key.strip())


def deepseek_chat(messages: list[dict], json_mode: bool = False, temperature: float = 0.4,
                  *, max_tokens: int = 2048, timeout: float = 120.0) -> str:
    """调用 DeepSeek OpenAI 兼容接口，返回完整文本。"""
    if not interview_llm_configured():
        raise InterviewProviderError("DeepSeek 未配置")
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {settings.deepseek_api_key.strip()}",
    }
    body: dict = {
        "model": settings.deepseek_model.strip() or "deepseek-chat",
        "messages": messages,
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    url = f"{settings.deepseek_base_url.rstrip('/')}/chat/completions"
    try:
        response = httpx.post(url, headers=headers, json=body, timeout=timeout)
        response.raise_for_status()
        data = response.json()
    except (httpx.HTTPError, json.JSONDecodeError) as reason:
        raise InterviewProviderError(f"DeepSeek 调用失败：{reason}") from reason
    try:
        content = data["choices"][0]["message"]["content"]
        if not isinstance(content, str):
            raise TypeError("message.content must be a string")
    except (KeyError, IndexError, TypeError) as reason:
        raise InterviewProviderError("DeepSeek 响应格式异常") from reason
    return content.strip()


def _extract_json(text: str):
    """从模型输出中提取 JSON（容忍 markdown 代码块与前后缀文本）。"""
    cleaned = re.sub(r"```(?:json)?", "", text).strip().strip("`").strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass
    for pattern in (r"\{[\s\S]*\}", r"\[[\s\S]*\]"):
        matched = re.search(pattern, cleaned)
        if matched:
            try:
                return json.loads(matched.group(0))
            except json.JSONDecodeError:
                continue
    raise InterviewProviderError("模型没有返回可解析的 JSON")


def _role_context_text(role: dict) -> str:
    skills = [f"{item.get('name', '')}（渗透率 {round((item.get('weight') or 0) * 100)}%）" for item in (role.get("skills") or [])[:12]]
    postings = [f"{item.get('title', '')}（{item.get('education') or '学历不限'}，{item.get('experience') or '经验不限'}）" for item in (role.get("postings") or [])[:5]]
    lines = [
        f"目标岗位：{role.get('name', '')}（岗位族：{role.get('field') or '未知'}）",
        f"招聘样本：约 {role.get('postingCount', 0)} 条 JD；趋势标签：{role.get('trendLabel') or '证据不足'}",
        "岗位核心技能：" + ("、".join(skills) if skills else "暂无"),
    ]
    if postings:
        lines.append("代表性 JD：" + "；".join(postings))
    education = role.get("educationRequirement") or {}
    if isinstance(education, dict) and education.get("dominant"):
        lines.append(f"主流学历要求：{education.get('dominant')}")
    if role.get("experienceRequirementMinYears"):
        lines.append(f"最低经验年限：{role.get('experienceRequirementMinYears')} 年")
    return "\n".join(lines)


def _candidate_context_text(resume_text: str, self_intro: str) -> str:
    parts = []
    if self_intro.strip():
        parts.append(f"候选人自我介绍：\n{self_intro.strip()[:2000]}")
    if resume_text.strip():
        parts.append(f"候选人简历全文（截取）：\n{resume_text.strip()[:4000]}")
    return "\n\n".join(parts) if parts else "（候选人未提供简历与自我介绍）"


# ---------------------------------------------------------------------------
# 生成面试问题
# ---------------------------------------------------------------------------

_QUESTION_SYSTEM_PROMPT = (
    "你是一位资深的中国互联网行业技术面试官，正在为候选人安排一场模拟面试。"
    "根据目标岗位的技能要求与候选人背景，设计有区分度的中文面试问题。"
    "只输出 JSON。"
)


def generate_questions(role: dict, resume_text: str, self_intro: str, count: int) -> list[dict]:
    """生成面试问题清单。返回 [{question, focus, referencePoints}]，带模板兜底。"""
    fallback = _fallback_questions(role, count)
    if not interview_llm_configured():
        return fallback
    prompt = (
        f"{_role_context_text(role)}\n\n{_candidate_context_text(resume_text, self_intro)}\n\n"
        f"请设计 {count} 道面试问题，要求：\n"
        "1. 至少一半问题紧扣岗位核心技能的实战深度，其余覆盖项目经历、协作与学习能力；\n"
        "2. 优先针对候选人简历/自我介绍中提到的经历追问细节；\n"
        "3. 每题给出 focus（考察点，10 字以内）和 referencePoints（参考答题要点，3-5 条字符串）；\n"
        '4. 只输出 JSON：{"questions": [{"question": "...", "focus": "...", "referencePoints": ["..."]}]}'
    )
    try:
        raw = deepseek_chat(
            [
                {"role": "system", "content": _QUESTION_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            json_mode=True,
        )
        payload = _extract_json(raw)
        questions = payload.get("questions") if isinstance(payload, dict) else payload
        if not isinstance(questions, list):
            raise InterviewProviderError("问题清单格式异常")
        cleaned: list[dict] = []
        for item in questions:
            if not isinstance(item, dict) or not str(item.get("question") or "").strip():
                continue
            cleaned.append({
                "question": str(item["question"]).strip(),
                "focus": str(item.get("focus") or "综合考察").strip()[:30],
                "referencePoints": [str(point).strip() for point in (item.get("referencePoints") or []) if str(point).strip()][:5],
            })
        return cleaned[:count] if cleaned else fallback
    except (InterviewProviderError, ValueError):
        return fallback


def _fallback_questions(role: dict, count: int) -> list[dict]:
    """DeepSeek 不可用时，基于岗位技能生成模板问题。"""
    skills = [item.get("name", "") for item in (role.get("skills") or []) if item.get("name")]
    top_skills = skills[: max(count - 3, 1)]
    questions: list[dict] = [
        {
            "question": "请先做一个简单的自我介绍，重点讲讲与目标岗位相关的经历。",
            "focus": "表达能力",
            "referencePoints": ["结构清晰", "突出岗位相关经历", "控制在 2 分钟内"],
        }
    ]
    for skill in top_skills:
        questions.append({
            "question": f"你在「{skill}」方面有哪些实际项目经验？请结合一个具体案例，说说你解决了什么问题、方案是怎么设计的。",
            "focus": f"{skill}实战",
            "referencePoints": ["有真实场景", "讲清个人贡献", "能说出取舍与结果"],
        })
    questions.append({
        "question": "讲一次你和团队协作解决困难问题的经历，你在其中的角色是什么？",
        "focus": "协作能力",
        "referencePoints": ["具体冲突或困难", "沟通方式", "最终结果"],
    })
    questions.append({
        "question": "如果入职后接触到你不熟悉的新技术或新业务，你会怎么快速上手？",
        "focus": "学习能力",
        "referencePoints": ["有方法论", "举实际例子", "时间预期合理"],
    })
    # Keep the requested question count stable even when a role has only a few indexed skills.
    generic = [
        ("请说明一次你在压力下推进任务的经历，你如何保证质量？", "压力与质量"),
        ("你通常如何验证自己的方案有效，并根据反馈调整？", "验证与复盘"),
        ("入职后你会如何制定前三个月的学习与交付计划？", "入职计划"),
    ]
    for question, focus in generic:
        if len(questions) >= count:
            break
        questions.append({"question": question, "focus": focus, "referencePoints": ["说明具体场景", "讲清个人行动", "给出结果或改进"]})
    return questions[:count]


# ---------------------------------------------------------------------------
# 点评回答
# ---------------------------------------------------------------------------

_EVALUATE_SYSTEM_PROMPT = (
    "你是一位严格的中文面试官，正在点评候选人的模拟面试回答。"
    "点评要具体、指出亮点与不足，但保持礼貌。只输出 JSON。"
)


def evaluate_answer(role: dict, question_item: dict, answer: str) -> dict:
    """点评单个回答。返回 {feedback, score, referencePoints}，带兜底。"""
    answer_text = (answer or "").strip()
    fallback_score = max(20, min(92, 25 + min(45, len(answer_text) // 3) + (25 if any(token in answer_text for token in ("因为", "因此", "结果", "负责", "通过")) else 10) + (10 if any(char.isdigit() for char in answer_text) else 0)))
    fallback = {
        "feedback": "回答已覆盖基本思路。建议补充你亲自采取的关键行动、量化结果，以及遇到阻碍时的取舍依据。" if fallback_score < 75 else "回答结构清晰，能够说明行动与结果。可以再补充复盘后的改进动作，让经验更具迁移性。",
        "score": fallback_score,
        "referencePoints": question_item.get("referencePoints") or [],
    }
    if not interview_llm_configured():
        return fallback
    prompt = (
        f"{_role_context_text(role)}\n\n"
        f"面试问题：{question_item.get('question', '')}\n（考察点：{question_item.get('focus', '')}）\n\n"
        f"候选人回答：\n{answer.strip()[:3000]}\n\n"
        "请点评这条回答。要求：\n"
        "1. feedback 为 80-160 字的中文点评，先肯定亮点，再指出最重要的 1-2 个不足；\n"
        "2. score 为 0-100 的整数评分；\n"
        '3. 只输出 JSON：{"feedback": "...", "score": 75}'
    )
    try:
        raw = deepseek_chat(
            [
                {"role": "system", "content": _EVALUATE_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            json_mode=True,
            temperature=0.3,
        )
        payload = _extract_json(raw)
        if not isinstance(payload, dict) or not str(payload.get("feedback") or "").strip():
            raise InterviewProviderError("点评格式异常")
        score = payload.get("score")
        try:
            score = max(0, min(100, round(float(score)))) if score is not None else None
        except (TypeError, ValueError):
            score = None
        return {
            "feedback": str(payload["feedback"]).strip(),
            "score": score,
            "referencePoints": question_item.get("referencePoints") or [],
        }
    except (InterviewProviderError, ValueError):
        return fallback


# ---------------------------------------------------------------------------
# 生成面试报告
# ---------------------------------------------------------------------------

_REPORT_SYSTEM_PROMPT = (
    "你是一位资深面试官，正在为候选人撰写模拟面试综合评估报告。"
    "报告用中文、语气专业且建设性。只输出 JSON。"
)


def generate_report(role: dict, questions: list[dict], self_intro: str) -> dict:
    """生成整场面试报告。返回带兜底的报告结构。"""
    scored = [item for item in questions if item.get("score") is not None]
    average = round(sum(item["score"] for item in scored) / len(scored)) if scored else None
    fallback = _fallback_report(role, questions, average)
    if not interview_llm_configured():
        return fallback
    transcript_lines = []
    for index, item in enumerate(questions, start=1):
        transcript_lines.append(f"问题{index}（{item.get('focus', '')}）：{item.get('question', '')}")
        transcript_lines.append(f"回答：{(item.get('answer') or '').strip()[:1200]}")
        if item.get("feedback"):
            transcript_lines.append(f"单题点评：{item['feedback']}")
    prompt = (
        f"{_role_context_text(role)}\n\n候选人自我介绍：{self_intro.strip()[:1000] or '（无）'}\n\n"
        f"面试逐字记录：\n" + "\n".join(transcript_lines) + "\n\n"
        "请生成综合评估报告。要求：\n"
        "1. overallScore 为 0-100 整数总分；summary 为 100-200 字总体评价；\n"
        "2. dimensions 为 3-5 个维度，每个 {name, score(0-100), comment(40 字内)}，至少覆盖 专业能力、表达沟通、岗位匹配；\n"
        "3. strengths 与 improvements 各 2-4 条短语；suggestions 为 2-4 条可执行的提升建议；\n"
        '4. 只输出 JSON：{"overallScore": 72, "summary": "...", "dimensions": [{"name": "专业能力", "score": 70, "comment": "..."}], "strengths": ["..."], "improvements": ["..."], "suggestions": ["..."]}'
    )
    try:
        raw = deepseek_chat(
            [
                {"role": "system", "content": _REPORT_SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            json_mode=True,
            temperature=0.3,
        )
        payload = _extract_json(raw)
        if not isinstance(payload, dict) or not str(payload.get("summary") or "").strip():
            raise InterviewProviderError("报告格式异常")
        dimensions = []
        for item in payload.get("dimensions") or []:
            if isinstance(item, dict) and str(item.get("name") or "").strip():
                dimension_score = _clamp_score(item.get("score"))
                dimensions.append({
                    "name": str(item["name"]).strip()[:20],
                    "score": dimension_score if dimension_score is not None else (average if average is not None else 60),
                    "comment": str(item.get("comment") or "").strip()[:80],
                })
        return {
            "overallScore": _clamp_score(payload.get("overallScore")) or (average if average is not None else 60),
            "summary": str(payload["summary"]).strip(),
            "dimensions": dimensions or fallback["dimensions"],
            "strengths": [str(text).strip() for text in (payload.get("strengths") or []) if str(text).strip()][:4],
            "improvements": [str(text).strip() for text in (payload.get("improvements") or []) if str(text).strip()][:4],
            "suggestions": [str(text).strip() for text in (payload.get("suggestions") or []) if str(text).strip()][:4],
            "provider": "deepseek",
        }
    except (InterviewProviderError, ValueError):
        return fallback


def _clamp_score(value) -> int | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return max(0, min(100, round(number)))


def _fallback_report(role: dict, questions: list[dict], average: int | None) -> dict:
    if average is None:
        average = 60
    strengths, improvements = [], []
    for item in questions:
        score = item.get("score")
        if score is None:
            continue
        if score >= 75 and len(strengths) < 4:
            strengths.append(f"{item.get('focus', '综合')}：回答质量较好")
        elif score < 60 and len(improvements) < 4:
            improvements.append(f"{item.get('focus', '综合')}：回答深度不足")
    skills = [item.get("name", "") for item in (role.get("skills") or [])[:3] if item.get("name")]
    return {
        "overallScore": average,
        "summary": (
            f"本场共回答 {len(questions)} 个问题，综合得分 {average} 分。"
            + (f"建议优先补强岗位核心技能：{'、'.join(skills)}。" if skills else "建议结合岗位核心技能继续补强。")
            + "（当前 LLM 未配置，报告由本地规则生成）"
        ),
        "dimensions": [
            {"name": "专业能力", "score": average, "comment": "基于逐题评分聚合"},
            {"name": "表达沟通", "score": min(100, average + 5), "comment": "基于回答完整度估算"},
            {"name": "岗位匹配", "score": max(0, average - 5), "comment": "结合岗位技能要求估算"},
        ],
        "strengths": strengths or ["完成了全部面试问题"],
        "improvements": improvements or ["回答可进一步结合具体项目案例"],
        "suggestions": ["围绕岗位高频技能准备 1-2 个可展开的项目案例"] + [f"系统补强「{skill}」相关的知识与实战" for skill in skills[:2]],
        "provider": "rules",
    }


# ---------------------------------------------------------------------------
# 语音转写（国内 ASR，OpenAI 兼容 /audio/transcriptions 协议）
# ---------------------------------------------------------------------------

def transcribe_audio(file_bytes: bytes, filename: str) -> str:
    """调用国内 ASR（默认阿里 DashScope 兼容模式）把录音转成文字。"""
    if not asr_configured():
        raise InterviewProviderError("语音识别未配置，请在 .env.local 中设置 INTERVIEW_ASR_API_KEY，或改用文字作答")
    url = f"{settings.interview_asr_base_url.rstrip('/')}/audio/transcriptions"
    headers = {"Authorization": f"Bearer {settings.interview_asr_api_key.strip()}"}
    files = {"file": (filename or "answer.webm", file_bytes)}
    data = {"model": settings.interview_asr_model.strip() or "paraformer-v2"}
    try:
        response = httpx.post(url, headers=headers, files=files, data=data, timeout=settings.interview_asr_timeout_seconds)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPError as reason:
        raise InterviewProviderError(f"语音识别调用失败：{reason}") from reason
    text = str(payload.get("text") or "").strip()
    if not text:
        raise InterviewProviderError("语音识别没有返回内容，请重试或改用文字作答")
    return text
