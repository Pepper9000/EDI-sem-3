const API_BASE_URL = (import.meta.env?.VITE_API_BASE_URL || 'http://127.0.0.1:8000').replace(/\/$/, '')

function describeError(payload, status) {
  const detail = payload?.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    return detail.map((item) => item.msg || JSON.stringify(item)).join('; ')
  }
  if (detail) return JSON.stringify(detail)
  if (payload?.message) return payload.message
  return `Request failed with status ${status}`
}

async function request(path, options = {}) {
  let response

  try {
    response = await fetch(`${API_BASE_URL}${path}`, {
      headers: {
        Accept: 'application/json',
        ...(options.body ? { 'Content-Type': 'application/json' } : {}),
        ...options.headers,
      },
      ...options,
    })
  } catch (error) {
    if (error instanceof TypeError) {
      throw new Error(`Cannot reach the DayPlan API at ${API_BASE_URL}. Confirm that FastAPI is running and CORS allows this frontend origin.`)
    }
    throw error
  }

  const contentType = response.headers.get('content-type') || ''
  const payload = contentType.includes('application/json')
    ? await response.json()
    : await response.text()

  if (!response.ok) {
    throw new Error(describeError(payload, response.status))
  }

  return payload
}

const api = {
  getTasks: () => request('/tasks'),
  createTask: (task) => request('/tasks', { method: 'POST', body: JSON.stringify(task) }),
  deleteTask: (taskId) => request(`/tasks/${taskId}`, { method: 'DELETE' }),
  getAvailability: () => request('/availability'),
  addAvailability: async (window) => {
    const payload = await request('/availability', {
      method: 'POST',
      body: JSON.stringify(window),
    })
    if (!payload?.window) throw new Error(payload?.message || 'The availability window was rejected.')
    return payload
  },
  deleteAvailability: (window) => {
    const query = new URLSearchParams({
      date: window.date,
      start_time: window.start_time,
      end_time: window.end_time,
    })
    return request(`/availability/window?${query}`, { method: 'DELETE' })
  },
  getEnergy: () => request('/energy'),
  setEnergy: (level) => request('/energy', { method: 'POST', body: JSON.stringify({ level }) }),
  getBiologicalState: () => request('/biological-state'),
  getSchedule: (date) => request(date ? `/schedule?date=${encodeURIComponent(date)}` : '/schedule'),
  getSettings: () => request('/settings'),
  updateSettings: (endOfDay) => request('/settings', {
    method: 'PUT',
    body: JSON.stringify({ end_of_day: endOfDay }),
  }),
  getFeedback: () => request('/feedback'),
  submitFeedback: (feedback) => request('/feedback', { method: 'POST', body: JSON.stringify(feedback) }),
  getProductivityInsights: () => request('/productivity-insights'),
  rescheduleTask: (taskId, { date, start_time }) => request(`/tasks/${taskId}/reschedule`, {
    method: 'POST',
    body: JSON.stringify({ date, start_time }),
  }),
  previewWeeklyAvailability: (payload) => request('/availability/weekly/preview', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
  addWeeklyAvailability: (payload) => request('/availability/weekly', {
    method: 'POST',
    body: JSON.stringify(payload),
  }),
}

export { API_BASE_URL, api }
