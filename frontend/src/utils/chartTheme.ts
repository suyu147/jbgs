/** Shared chart language for the student workspace; labels accompany all semantics. */
export const chartTheme = {
  primary: '#176b5b', comparison: '#66859a', neutral: '#7e9286', warning: '#967342',
  text: '#203b33', muted: '#586c62', line: '#d5e1d8', grid: '#e6ede7',
  palette: ['#176b5b', '#66859a', '#967342', '#7e9286'],
}
export function escapeChartText(value: unknown) {
  return String(value ?? '').replace(/[&<>"']/g, char => ({'&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'}[char] || char))
}
