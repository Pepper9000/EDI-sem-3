import { useEffect, useEffectEvent, useState } from 'react'
import {
  Area,
  AreaChart,
  CartesianGrid,
  ReferenceLine,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'
import { api } from './services/api.js'

const defaultTaskForm = { name: '', difficulty: 3, duration: 60, importance: 3, deadline: '' }
const pageLoadedAt = new Date()
const pageDate = new Date(pageLoadedAt.getTime() - pageLoadedAt.getTimezoneOffset() * 60_000).toISOString().slice(0, 10)
const defaultAvailabilityForm = { date: pageDate, start_time: '09:00', end_time: '12:00' }
const defaultWeeklyForm = { start_time: '09:00', end_time: '12:00' }
const WEEKDAYS = [
  { key: 'Monday', short: 'Mon' },
  { key: 'Tuesday', short: 'Tue' },
  { key: 'Wednesday', short: 'Wed' },
  { key: 'Thursday', short: 'Thu' },
  { key: 'Friday', short: 'Fri' },
  { key: 'Saturday', short: 'Sat' },
  { key: 'Sunday', short: 'Sun' },
]
const energyForHour = (hour) => {
  if (hour >= 9 && hour < 12) return 5
  if (hour >= 12 && hour < 14) return 3
  if (hour >= 14 && hour < 17) return 4
  if (hour >= 17 && hour < 20) return 3
  if (hour >= 20 && hour < 22) return 2
  return 1
}
const formatMinutes = (minutes = 0) => {
  const hours = Math.floor(minutes / 60)
  const remainder = minutes % 60
  if (hours && remainder) return `${hours}h ${remainder}m`
  if (hours) return `${hours}h`
  return `${remainder}m`
}
const hourLabel = (hour) => `${String(hour).padStart(2, '0')}:00`
const timeToMinutes = (str = '00:00') => {
  const [h, m] = str.split(':').map(Number)
  return h * 60 + m
}
const minutesToTime = (minutes = 0) => {
  const h = Math.floor(minutes / 60)
  const m = minutes % 60
  return `${String(h).padStart(2, '0')}:${String(m).padStart(2, '0')}`
}
const completionStatusFor = (task, records) => {
  const outcome = [...records].reverse().find((item) => item.task_id === task.task_id || (item.task_id == null && item.task_name === task.task))
  return outcome?.completion_status ?? (outcome ? outcome.completed ? 'completed' : 'not completed' : null)
}

const feedbackChoices = {
  completion_status: [['completed', 'Completed'], ['partial', 'Partially done'], ['skipped', 'Skipped']],
  difficulty_feedback: [['too_easy', 'Too easy'], ['about_right', 'About right'], ['too_hard', 'Too hard']],
  timing_feedback: [['too_early', 'Too early'], ['good_time', 'Good time'], ['too_late', 'Too late']],
  energy_impact: [['energized', 'More energized'], ['same', 'About the same'], ['drained', 'Drained']],
}

function computeFallbackHorizon(baseDateStr) {
  const [year, month, day] = baseDateStr.split('-').map(Number)
  const base = new Date(year, month - 1, day)
  return Array.from({ length: 7 }, (_, i) => {
    const current = new Date(base.getFullYear(), base.getMonth(), base.getDate() + i)
    const y = current.getFullYear()
    const m = String(current.getMonth() + 1).padStart(2, '0')
    const d = String(current.getDate()).padStart(2, '0')
    const dateStr = `${y}-${m}-${d}`
    return {
      date: dateStr,
      day_name: current.toLocaleDateString('en-US', { weekday: 'long' }),
      short_date: current.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }),
      is_today: i === 0,
      available_minutes: 0,
      scheduled_minutes: 0,
      unused_minutes: 0,
      unscheduled_count: 0,
      schedule: [],
    }
  })
}

const GRID_START_HOUR = 7
const GRID_END_HOUR = 23
const GRID_HOURS = Array.from({ length: GRID_END_HOUR - GRID_START_HOUR + 1 }, (_, i) => GRID_START_HOUR + i)
const PIXELS_PER_MINUTE = 1
const GRID_HEIGHT = (GRID_END_HOUR - GRID_START_HOUR) * 60 * PIXELS_PER_MINUTE

function App() {
  const [activeTab, setActiveTab] = useState('planner') // 'planner' | 'calendar'
  const [tasks, setTasks] = useState([])
  const [availability, setAvailability] = useState([])
  const [feedback, setFeedback] = useState([])
  const [scheduleData, setScheduleData] = useState(null)
  const [selectedDate, setSelectedDate] = useState(pageDate)
  const [biologicalState, setBiologicalState] = useState(null)
  const [settings, setSettings] = useState({ end_of_day: '22:00' })
  const [taskForm, setTaskForm] = useState(defaultTaskForm)
  const [availabilityForm, setAvailabilityForm] = useState(defaultAvailabilityForm)
  const [availabilityMode, setAvailabilityMode] = useState('single') // 'single' | 'weekly'
  const [weeklyForm, setWeeklyForm] = useState(defaultWeeklyForm)
  const [selectedWeekdays, setSelectedWeekdays] = useState(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'])
  const [endOfDayDraft, setEndOfDayDraft] = useState('22:00')
  const [feedbackForm, setFeedbackForm] = useState({ taskId: '', completion_status: '', difficulty_feedback: '', timing_feedback: '', energy_impact: '' })
  const [selectedTaskDetails, setSelectedTaskDetails] = useState(null)
  const [rescheduleForm, setRescheduleForm] = useState({ date: pageDate, start_time: '09:00' })
  const [draggedTask, setDraggedTask] = useState(null)
  const [dragOverDate, setDragOverDate] = useState(null)
  const [busy, setBusy] = useState('')
  const [error, setError] = useState('')
  const [statusMessage, setStatusMessage] = useState('Loading seven-day plan…')

  const refreshDashboard = async () => {
    const [taskData, schedule, windows, energy, bio, feedbackData, settingData] = await Promise.all([
      api.getTasks(), api.getSchedule(), api.getAvailability(), api.getEnergy(),
      api.getBiologicalState(), api.getFeedback(), api.getSettings(),
    ])
    setTasks(taskData)
    setScheduleData(schedule)
    setAvailability(windows)
    setBiologicalState({ ...bio, manual_energy: energy.energy })
    setFeedback(feedbackData)
    setSettings(settingData)
    setEndOfDayDraft(settingData.end_of_day)
  }

  const loadDashboard = useEffectEvent(async () => {
    try {
      await refreshDashboard()
      setStatusMessage('Your seven-day plan is ready.')
    } catch (loadError) {
      setError(loadError.message)
      setStatusMessage('Could not load DayPlan data.')
    }
  })

  useEffect(() => {
    const loadId = window.setTimeout(loadDashboard, 0)
    return () => window.clearTimeout(loadId)
  }, [])

  const runAction = async (key, action) => {
    setBusy(key)
    setError('')
    try {
      await action()
    } catch (actionError) {
      setError(actionError.message)
      setStatusMessage('That action could not be completed.')
    } finally {
      setBusy('')
    }
  }

  const handleTaskSubmit = async (event) => {
    event.preventDefault()
    await runAction('task', async () => {
      const payload = { ...taskForm, duration: Number(taskForm.duration), deadline: taskForm.deadline || null }
      const result = await api.createTask(payload)
      setTaskForm(defaultTaskForm)
      setStatusMessage(result.message)
      await refreshDashboard()
    })
  }

  const handleTaskDelete = async (task) => {
    if (!window.confirm(`Remove “${task.name}” from your task list?`)) return
    await runAction(`delete-task-${task.id}`, async () => {
      const result = await api.deleteTask(task.id)
      if (selectedTaskDetails?.task_id === task.id) {
        setSelectedTaskDetails(null)
      }
      setStatusMessage(result.message)
      await refreshDashboard()
    })
  }

  const handleAvailabilitySubmit = async (event) => {
    event.preventDefault()
    if (availabilityForm.start_time >= availabilityForm.end_time) {
      setError('End time must be later than start time.')
      return
    }
    await runAction('availability', async () => {
      const result = await api.addAvailability(availabilityForm)
      setStatusMessage(result.message)
      await refreshDashboard()
    })
  }

  const handleAvailabilityDelete = async (window) => {
    await runAction(`delete-window-${window.date}-${window.start_time}`, async () => {
      const result = await api.deleteAvailability(window)
      setStatusMessage(result.message)
      await refreshDashboard()
    })
  }

  const handleWeeklyAvailabilitySubmit = async (event) => {
    event.preventDefault()
    if (weeklyForm.start_time >= weeklyForm.end_time) {
      setError('End time must be later than start time.')
      return
    }
    if (selectedWeekdays.length === 0) {
      setError('Select at least one weekday.')
      return
    }
    await runAction('weekly-availability', async () => {
      const result = await api.addWeeklyAvailability({
        weekdays: selectedWeekdays,
        start_time: weeklyForm.start_time,
        end_time: weeklyForm.end_time,
      })
      setStatusMessage(result.message)
      await refreshDashboard()
    })
  }

  const toggleWeekday = (dayName) => {
    setSelectedWeekdays((prev) =>
      prev.includes(dayName) ? prev.filter((d) => d !== dayName) : [...prev, dayName]
    )
  }

  const handleSchedule = async () => {
    await runAction('schedule', async () => {
      const result = await api.getSchedule()
      setScheduleData(result)
      setStatusMessage(result.message)
    })
  }

  const handleEnergySet = async (level) => {
    await runAction('energy', async () => {
      const result = await api.setEnergy(level)
      await refreshDashboard()
      setStatusMessage(`Manual energy set to ${result.energy}/5.`)
    })
  }

  const handleEndOfDaySubmit = async (event) => {
    event.preventDefault()
    if (endOfDayDraft < '17:00' || endOfDayDraft > '23:59') {
      setError('Choose an end-of-day time between 17:00 and 23:59.')
      return
    }
    await runAction('settings', async () => {
      const result = await api.updateSettings(endOfDayDraft)
      setSettings({ end_of_day: result.end_of_day })
      setStatusMessage(`Scheduling cutoff set to ${result.end_of_day}.`)
      setScheduleData(await api.getSchedule())
    })
  }

  const selectedFeedbackTask = tasks.find((task) => String(task.id) === feedbackForm.taskId)
  const handleFeedbackSubmit = async (event) => {
    event.preventDefault()
    if (!selectedFeedbackTask) {
      setError('Choose a task before sending feedback.')
      return
    }
    if (!feedbackForm.completion_status || !feedbackForm.difficulty_feedback || !feedbackForm.timing_feedback) {
      setError('Choose an answer for completion, difficulty, and timing.')
      return
    }
    await runAction('feedback', async () => {
      const result = await api.submitFeedback({
        task_name: selectedFeedbackTask.name,
        task_id: selectedFeedbackTask.id,
        energy: biologicalState?.manual_energy ?? 3,
        difficulty: selectedFeedbackTask.difficulty,
        duration: selectedFeedbackTask.duration,
        completed: feedbackForm.completion_status === 'completed',
        completion_status: feedbackForm.completion_status,
        difficulty_feedback: feedbackForm.difficulty_feedback,
        timing_feedback: feedbackForm.timing_feedback,
        energy_impact: feedbackForm.energy_impact || null,
      })
      setFeedbackForm({ taskId: '', completion_status: '', difficulty_feedback: '', timing_feedback: '', energy_impact: '' })
      setStatusMessage(result.message)
      setFeedback(await api.getFeedback())
    })
  }

  // Exactly seven consecutive days in horizon
  const horizonDays = scheduleData?.days && scheduleData.days.length === 7
    ? scheduleData.days
    : computeFallbackHorizon(pageDate)

  const selectedDay = horizonDays.find((d) => d.date === selectedDate) || horizonDays[0]
  const activeDate = selectedDay.date
  const activeIsToday = selectedDay.is_today

  const schedule = selectedDay.schedule ?? []
  const taskEntries = schedule.filter((entry) => entry.type === 'task')
  const breakEntries = schedule.filter((entry) => entry.type === 'break')
  const unscheduledEntries = schedule.filter((entry) => entry.type === 'unscheduled')
  const availableMinutes = selectedDay.available_minutes ?? 0
  const scheduledMinutes = selectedDay.scheduled_minutes ?? 0
  const unusedMinutes = selectedDay.unused_minutes ?? 0

  // Availability windows on the selected date
  const selectedDayAvailability = availability.filter((w) => w.date === activeDate)

  // Weekly availability preview across 7-day horizon
  const weeklyPreview = horizonDays
    .filter((d) => selectedWeekdays.some((w) => w.toLowerCase() === d.day_name.toLowerCase()))
    .map((d) => {
      const exists = availability.some(
        (w) => w.date === d.date && w.start_time === weeklyForm.start_time && w.end_time === weeklyForm.end_time
      )
      return {
        ...d,
        exists,
      }
    })

  const willAddCount = weeklyPreview.filter((p) => !p.exists).length
  const alreadyExistsCount = weeklyPreview.filter((p) => p.exists).length

  // Collect authoritative unscheduled tasks list across horizon
  const scheduledTaskIds = new Set(
    horizonDays.flatMap((d) => (d.schedule || []).filter((e) => e.type === 'task').map((e) => e.task_id))
  )
  const unscheduledTasksList = scheduleData?.unscheduled_tasks?.length
    ? scheduleData.unscheduled_tasks
    : tasks.filter((t) => !scheduledTaskIds.has(t.id)).map((t) => ({
        task_id: t.id,
        task: t.name,
        difficulty: t.difficulty,
        importance: t.importance,
        duration: t.duration,
        deadline: t.deadline,
        type: 'unscheduled',
        reason: 'No suitable slot found within the 7-day planning horizon.',
      }))

  const completedFeedback = feedback.filter((entry) => entry.completion_status === 'completed' || (entry.completion_status == null && entry.completed))
  const skippedFeedback = feedback.filter((entry) => entry.completion_status === 'skipped')
  const partialFeedback = feedback.filter((entry) => entry.completion_status === 'partial')
  const ratedFeedback = feedback.filter((entry) => Number.isFinite(entry.rating))
  const averageRating = ratedFeedback.length
    ? (ratedFeedback.reduce((total, entry) => total + entry.rating, 0) / ratedFeedback.length).toFixed(1)
    : '—'
  const chartData = Array.from({ length: 24 }, (_, hour) => ({ hour, energy: energyForHour(hour) }))
  const now = pageLoadedAt
  const currentHour = now.getHours() + now.getMinutes() / 60
  const currentEnergy = biologicalState?.effective_energy ?? 3
  const hardestTask = tasks.reduce((hardest, task) => (!hardest || task.difficulty > hardest.difficulty ? task : hardest), null)

  const recommendation = !availability.length
    ? 'Add an availability window to give the scheduler room to place tasks.'
    : !tasks.length
      ? 'Add a task to build a plan around your available time.'
      : unscheduledEntries.length
        ? `${unscheduledEntries.length} task${unscheduledEntries.length === 1 ? '' : 's'} could not fit on this date.`
        : unusedMinutes <= 60
          ? 'You have limited unused availability on this date; keep new tasks short.'
          : hardestTask && hardestTask.difficulty >= currentEnergy
            ? `Estimated energy currently fits higher-difficulty work such as ${hardestTask.name}.`
            : `Estimated energy is ${currentEnergy}/5; a task near that difficulty may fit this period.`

  const onSelectDate = (newDate) => {
    setSelectedDate(newDate)
    setAvailabilityForm((prev) => ({ ...prev, date: newDate }))
  }

  // Open Task Details Panel
  const openTaskDetails = (task, date) => {
    const fullTask = tasks.find((t) => t.id === task.task_id || t.id === task.id)
    const detail = {
      ...task,
      task_id: task.task_id || task.id,
      name: task.task || task.name,
      difficulty: task.difficulty ?? fullTask?.difficulty ?? 3,
      importance: task.importance ?? fullTask?.importance ?? 3,
      duration: task.duration ?? fullTask?.duration ?? 60,
      deadline: task.deadline ?? fullTask?.deadline ?? null,
      date: date || task.date || null,
      start_time: task.start_time || null,
      end_time: task.end_time || null,
    }
    setSelectedTaskDetails(detail)
    setRescheduleForm({
      date: date || task.date || pageDate,
      start_time: task.start_time || '09:00',
    })
  }

  // Explicit Reschedule Action Handler
  const handleExplicitReschedule = async (event) => {
    event.preventDefault()
    if (!selectedTaskDetails?.task_id) return
    await runAction('reschedule', async () => {
      const result = await api.rescheduleTask(selectedTaskDetails.task_id, {
        date: rescheduleForm.date,
        start_time: rescheduleForm.start_time,
      })
      setStatusMessage(result.message)
      setSelectedTaskDetails(null)
      await refreshDashboard()
    })
  }

  // Drag and Drop Handlers
  const handleDragStart = (event, task, sourceDate) => {
    const taskId = task.task_id || task.id
    const payload = {
      task_id: taskId,
      task: task.task || task.name,
      duration: task.duration,
      sourceDate,
    }
    setDraggedTask(payload)
    event.dataTransfer.setData('text/plain', JSON.stringify(payload))
    event.dataTransfer.effectAllowed = 'move'
  }

  const handleDragOver = (event, targetDate) => {
    event.preventDefault()
    event.dataTransfer.dropEffect = 'move'
    if (dragOverDate !== targetDate) {
      setDragOverDate(targetDate)
    }
  }

  const handleDragLeave = () => {
    setDragOverDate(null)
  }

  const handleDrop = async (event, targetDate) => {
    event.preventDefault()
    setDragOverDate(null)
    let taskToMove = draggedTask
    if (!taskToMove) {
      try {
        const dataStr = event.dataTransfer.getData('text/plain')
        if (dataStr) taskToMove = JSON.parse(dataStr)
      } catch {
        // ignore parse error
      }
    }
    if (!taskToMove?.task_id) return

    const rect = event.currentTarget.getBoundingClientRect()
    const offsetY = Math.max(0, event.clientY - rect.top)
    const minuteFrom7am = Math.min(GRID_HEIGHT, offsetY)
    const rawMinutes = GRID_START_HOUR * 60 + minuteFrom7am
    // 15-minute snap
    const snappedMinutes = Math.floor(rawMinutes / 15) * 15
    const duration = taskToMove.duration || 60
    const maxStart = GRID_END_HOUR * 60 - duration
    const clampedMinutes = Math.max(GRID_START_HOUR * 60, Math.min(snappedMinutes, maxStart))
    const start_time = minutesToTime(clampedMinutes)

    await runAction('reschedule', async () => {
      const result = await api.rescheduleTask(taskToMove.task_id, {
        date: targetDate,
        start_time,
      })
      setStatusMessage(result.message)
      await refreshDashboard()
    })
  }

  const cutoffMinutes = timeToMinutes(settings.end_of_day)
  const cutoffTop = (cutoffMinutes - GRID_START_HOUR * 60) * PIXELS_PER_MINUTE

  return (
    <div className="app-shell">
      <header className="topbar">
        <a className="brand" href="#daily-flow" aria-label="DayPlan home">
          <span className="brand-mark">D</span>
          <span>DayPlan<span className="brand-period">.</span></span>
        </a>

        {/* Primary View Navigation: Planner vs Calendar */}
        <nav aria-label="Primary navigation">
          <button
            type="button"
            className={activeTab === 'planner' ? 'nav-link active' : 'nav-link'}
            onClick={() => setActiveTab('planner')}
            aria-current={activeTab === 'planner' ? 'page' : undefined}
          >
            Planner
          </button>
          <button
            type="button"
            className={activeTab === 'calendar' ? 'nav-link active' : 'nav-link'}
            onClick={() => setActiveTab('calendar')}
            aria-current={activeTab === 'calendar' ? 'page' : undefined}
          >
            Calendar
          </button>
        </nav>

        <div className="date-stamp">
          <span className="status-dot" />
          {activeDate}{activeIsToday ? ' (Today)' : ''}
        </div>
      </header>

      {/* PLANNER VIEW */}
      {activeTab === 'planner' ? (
        <main className="dashboard" id="daily-flow">
          <section className="page-heading">
            <div>
              <p className="eyebrow">STRICT SEVEN-DAY PLANNING HORIZON</p>
              <h1>{activeIsToday ? 'Today’s flow' : `${selectedDay.day_name} flow`}</h1>
              <p className="heading-copy">Viewing {activeDate} · Exactly seven consecutive calendar days planned.</p>
            </div>
            <div className="live-status"><span className="status-dot" />{statusMessage}</div>
          </section>
          {error ? <div className="error-banner" role="alert">{error}</div> : null}

          {/* Exactly seven day tabs / selectors */}
          <section className="day-selector-section" aria-label="Seven-day horizon tabs">
            <div className="day-selector-header">
              <span className="day-selector-label">SELECT DAY (7-DAY HORIZON)</span>
              <span className="day-selector-range">{horizonDays[0]?.date} to {horizonDays[6]?.date}</span>
            </div>
            <div className="day-selector" role="tablist">
              {horizonDays.map((day) => {
                const isSelected = day.date === activeDate
                const dayTasks = (day.schedule || []).filter((e) => e.type === 'task')
                return (
                  <button
                    key={day.date}
                    type="button"
                    role="tab"
                    className={`day-tab ${isSelected ? 'active' : ''} ${day.is_today ? 'is-today' : ''}`}
                    aria-selected={isSelected}
                    onClick={() => onSelectDate(day.date)}
                  >
                    <span className="day-tab-name">{day.is_today ? 'Today' : day.day_name.slice(0, 3)}</span>
                    <span className="day-tab-date">{day.short_date || day.date.slice(5)}</span>
                    <span className="day-tab-badge">{dayTasks.length} {dayTasks.length === 1 ? 'task' : 'tasks'}</span>
                  </button>
                )
              })}
            </div>
          </section>

          <section className="kpi-grid" aria-label="Day at a glance">
            <article className="kpi-card">
              <span className="kpi-label">ESTIMATED ENERGY</span>
              <strong>{currentEnergy}<small> / 5</small></strong>
              <span className="kpi-foot">Manual input {biologicalState?.manual_energy ?? '—'}/5</span>
            </article>
            <article className="kpi-card">
              <span className="kpi-label">TASKS SCHEDULED ({selectedDay.short_date || activeDate})</span>
              <strong>{taskEntries.length}<small> / {tasks.length} total</small></strong>
              <span className="kpi-foot">{unscheduledEntries.length ? `${unscheduledEntries.length} unplaced on this day` : `${formatMinutes(scheduledMinutes)} planned`}</span>
            </article>
            <article className="kpi-card">
              <span className="kpi-label">UNUSED AVAILABILITY</span>
              <strong>{formatMinutes(unusedMinutes)}</strong>
              <span className="kpi-foot">{formatMinutes(availableMinutes)} available on this day</span>
            </article>
            <article className="kpi-card">
              <span className="kpi-label">FEEDBACK SIGNAL</span>
              <strong>{feedback.length}<small> entries</small></strong>
              <span className="kpi-foot">Current backend session</span>
            </article>
          </section>

          {/* Weekly Overview Section */}
          <section className="panel weekly-overview-panel" id="weekly-overview">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">SEVEN-DAY OVERVIEW · {horizonDays[0]?.date} TO {horizonDays[6]?.date}</p>
                <h2>Weekly horizon overview</h2>
              </div>
              <span className="subtle-pill">Strict 7 days · Click day to inspect</span>
            </div>
            <div className="weekly-grid">
              {horizonDays.map((day) => {
                const isSelected = day.date === activeDate
                const dayTasks = (day.schedule || []).filter((e) => e.type === 'task')
                return (
                  <div
                    key={day.date}
                    className={`weekly-card ${isSelected ? 'active-card' : ''}`}
                    onClick={() => onSelectDate(day.date)}
                    role="button"
                    tabIndex={0}
                    onKeyDown={(e) => {
                      if (e.key === 'Enter' || e.key === ' ') {
                        onSelectDate(day.date)
                      }
                    }}
                  >
                    <div className="weekly-card-head">
                      <div>
                        <strong>{day.is_today ? 'Today' : day.day_name}</strong>
                        <span className="weekly-date-sub">{day.short_date || day.date}</span>
                      </div>
                      {isSelected ? <span className="selected-indicator">Selected</span> : null}
                    </div>
                    <div className="weekly-card-metrics">
                      <span>{formatMinutes(day.scheduled_minutes)} sched.</span>
                      <span>{formatMinutes(day.available_minutes)} avail.</span>
                    </div>
                    <div className="weekly-card-tasks">
                      {dayTasks.length ? dayTasks.map((t) => (
                        <div key={t.task_id || t.task} className="weekly-task-chip">
                          <span className="task-chip-time">{t.start_time}</span>
                          <strong className="task-chip-name">{t.task}</strong>
                          <span className="task-chip-dur">{t.duration}m</span>
                        </div>
                      )) : <span className="weekly-empty-text">No tasks</span>}
                    </div>
                  </div>
                )
              })}
            </div>

            {scheduleData?.unscheduled_tasks?.length ? (
              <div className="unplaced-overview-box">
                <div className="unplaced-box-title">
                  <span className="legend-dot unscheduled-dot" />
                  <strong>Unplaced tasks ({scheduleData.unscheduled_tasks.length}) within 7-day horizon:</strong>
                </div>
                <div className="unplaced-box-list">
                  {scheduleData.unscheduled_tasks.map((item) => (
                    <div key={item.task_id || item.task} className="unplaced-box-row">
                      <div>
                        <strong>{item.task}</strong>
                        <span className="unplaced-meta">{item.duration} min · Difficulty {item.difficulty}/5 · Importance {item.importance}/5</span>
                      </div>
                      <p className="reason-text">{item.reason}</p>
                    </div>
                  ))}
                </div>
              </div>
            ) : null}
          </section>

          <section className="content-grid energy-grid" id="energy">
            <article className="panel energy-panel">
              <div className="panel-heading">
                <div>
                  <p className="eyebrow">ESTIMATED PATTERN</p>
                  <h2>Energy through the day</h2>
                </div>
                <span className="subtle-pill">Heuristic estimate · 1–5</span>
              </div>
              <div className="chart-wrap">
                <ResponsiveContainer width="100%" height="100%">
                  <AreaChart data={chartData} margin={{ top: 12, right: 14, left: -18, bottom: 0 }}>
                    <defs>
                      <linearGradient id="energyFill" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="0%" stopColor="#18D6C1" stopOpacity={0.3} />
                        <stop offset="100%" stopColor="#18D6C1" stopOpacity={0.02} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid vertical={false} stroke="rgba(143,166,174,.12)" />
                    <XAxis dataKey="hour" type="number" domain={[0, 23]} ticks={[0, 3, 6, 9, 12, 15, 18, 21]} tickFormatter={hourLabel} axisLine={false} tickLine={false} />
                    <YAxis domain={[1, 5]} ticks={[1, 2, 3, 4, 5]} axisLine={false} tickLine={false} />
                    <Tooltip labelFormatter={(hour) => hourLabel(Number(hour))} formatter={(value) => [`${value}/5`, 'Estimated readiness']} contentStyle={{ background: '#122A35', border: '1px solid #29424C', borderRadius: 8, color: '#E8F1F3' }} />
                    {activeIsToday ? (
                      <ReferenceLine x={currentHour} stroke="#F2B84B" strokeDasharray="4 4" label={{ value: 'NOW', fill: '#F2B84B', fontSize: 10, position: 'insideTopRight' }} />
                    ) : null}
                    <Area type="monotone" dataKey="energy" stroke="#18D6C1" strokeWidth={2.5} fill="url(#energyFill)" activeDot={{ r: 4, fill: '#18D6C1' }} />
                  </AreaChart>
                </ResponsiveContainer>
              </div>
              <div className="chart-legend">
                <span><i className="legend-line" />Estimated energy</span>
                {activeIsToday ? <span><i className="legend-now" />Current time</span> : null}
                <span>Based on existing hour-of-day rules</span>
              </div>
              <div className="manual-energy-row">
                <span>Manual energy</span>
                <div role="group" aria-label="Set manual energy from one to five">
                  {[1, 2, 3, 4, 5].map((level) => (
                    <button className={biologicalState?.manual_energy === level ? 'energy-choice selected' : 'energy-choice'} type="button" key={level} aria-pressed={biologicalState?.manual_energy === level} onClick={() => handleEnergySet(level)} disabled={Boolean(busy)}>{level}</button>
                  ))}
                </div>
              </div>
            </article>

            <article className="panel recommendation-panel">
              <div className="recommendation-icon" aria-hidden="true">↗</div>
              <p className="eyebrow">DAYPLAN RECOMMENDATION</p>
              <h2>Make room for what matters.</h2>
              <p className="recommendation-copy">{recommendation}</p>
              <div className="recommendation-meta">
                <span>Energy match</span>
                <strong>{currentEnergy}/5 estimated</strong>
              </div>
              <button className="button button-primary button-wide" type="button" onClick={handleSchedule} disabled={Boolean(busy)}>
                {busy === 'schedule' ? 'Aligning…' : 'Auto-align 7 days'}<span aria-hidden="true">→</span>
              </button>
              <p className="fine-print">Distributes tasks across your 7-day horizon respecting energy, deadlines, and availability.</p>
            </article>
          </section>

          <section className="content-grid setup-grid" id="tasks">
            <article className="panel task-panel">
              <div className="panel-heading">
                <div><p className="eyebrow">TASK INTAKE</p><h2>Add a task</h2></div>
                <span className="subtle-pill">{tasks.length} in queue</span>
              </div>
              <form className="form-stack" onSubmit={handleTaskSubmit}>
                <label className="field-label">Task name<input required minLength="1" maxLength="120" value={taskForm.name} onChange={(event) => setTaskForm({ ...taskForm, name: event.target.value })} placeholder="e.g. Prepare project brief" /></label>
                <div className="two-fields">
                  <label className="field-label">Duration <span className="input-unit">minutes</span><input type="number" min="1" step="15" required value={taskForm.duration} onChange={(event) => setTaskForm({ ...taskForm, duration: event.target.value })} /></label>
                  <label className="field-label">Deadline <span className="input-unit">optional</span><input type="date" value={taskForm.deadline} onChange={(event) => setTaskForm({ ...taskForm, deadline: event.target.value })} /></label>
                </div>
                <div className="two-fields">
                  <label className="field-label">Difficulty<output>{taskForm.difficulty}/5</output><input type="range" min="1" max="5" value={taskForm.difficulty} onChange={(event) => setTaskForm({ ...taskForm, difficulty: Number(event.target.value) })} /></label>
                  <label className="field-label">Importance<output>{taskForm.importance}/5</output><input type="range" min="1" max="5" value={taskForm.importance} onChange={(event) => setTaskForm({ ...taskForm, importance: Number(event.target.value) })} /></label>
                </div>
                <button className="button button-secondary" type="submit" disabled={Boolean(busy)}>{busy === 'task' ? 'Adding task…' : 'Add to task list'}</button>
              </form>
            </article>

            <article className="panel availability-panel">
              <div className="panel-heading">
                <div><p className="eyebrow">TIME THAT’S YOURS</p><h2>Availability & fit ({selectedDay.short_date || activeDate})</h2></div>
                <span className="subtle-pill">Cutoff {settings.end_of_day}</span>
              </div>
              <div className="capacity-summary">
                <div><span>Available</span><strong>{formatMinutes(availableMinutes)}</strong></div>
                <div><span>Scheduled</span><strong>{formatMinutes(scheduledMinutes)}</strong></div>
                <div><span>Unused</span><strong>{formatMinutes(unusedMinutes)}</strong></div>
              </div>
              <p className={`fit-status ${unscheduledEntries.length ? 'fit-warning' : taskEntries.length ? 'fit-good' : ''}`}>
                {selectedDayAvailability.length === 0
                  ? `No availability configured for ${selectedDay.short_date || activeDate}.`
                  : taskEntries.length === 0 && unscheduledEntries.length === 0
                    ? `No tasks scheduled on ${selectedDay.short_date || activeDate}.`
                    : unscheduledEntries.length
                      ? `${unscheduledEntries.length} task${unscheduledEntries.length === 1 ? '' : 's'} could not be scheduled.`
                      : `All tasks assigned to ${selectedDay.short_date || activeDate} fit comfortably.`}
              </p>
              <div className="window-list">
                {selectedDayAvailability.length ? selectedDayAvailability.map((window, index) => (
                  <div className="window-row" key={`${window.date}-${window.start_time}-${window.end_time}-${index}`}>
                    <span className="window-date">{window.date}</span>
                    <strong>{window.start_time} <span>–</span> {window.end_time}</strong>
                    <button className="icon-button" type="button" aria-label={`Remove window ${window.start_time} to ${window.end_time}`} onClick={() => handleAvailabilityDelete(window)} disabled={Boolean(busy)} title="Remove window">×</button>
                  </div>
                )) : <p className="empty-note">No availability windows configured for {selectedDay.short_date || activeDate}.</p>}
              </div>
              {/* Availability Mode Toggle */}
              <div className="availability-mode-toggle" role="tablist" aria-label="Availability mode">
                <button
                  type="button"
                  className={`mode-tab ${availabilityMode === 'single' ? 'active' : ''}`}
                  onClick={() => setAvailabilityMode('single')}
                  role="tab"
                  aria-selected={availabilityMode === 'single'}
                >
                  Single day window
                </button>
                <button
                  type="button"
                  className={`mode-tab ${availabilityMode === 'weekly' ? 'active' : ''}`}
                  onClick={() => setAvailabilityMode('weekly')}
                  role="tab"
                  aria-selected={availabilityMode === 'weekly'}
                >
                  Add weekly availability
                </button>
              </div>

              {availabilityMode === 'single' ? (
                <form className="availability-form" onSubmit={handleAvailabilitySubmit}>
                  <label className="field-label">Date<input type="date" required value={availabilityForm.date} onChange={(event) => setAvailabilityForm({ ...availabilityForm, date: event.target.value })} /></label>
                  <label className="field-label">From<input type="time" required value={availabilityForm.start_time} onChange={(event) => setAvailabilityForm({ ...availabilityForm, start_time: event.target.value })} /></label>
                  <label className="field-label">To<input type="time" required value={availabilityForm.end_time} onChange={(event) => setAvailabilityForm({ ...availabilityForm, end_time: event.target.value })} /></label>
                  <button className="button button-small" type="submit" disabled={Boolean(busy)}>{busy === 'availability' ? 'Adding…' : 'Add window'}</button>
                </form>
              ) : (
                <form className="weekly-availability-form" onSubmit={handleWeeklyAvailabilitySubmit}>
                  <div className="weekday-picker-header">
                    <span className="field-title">Select weekdays (within 7-day horizon)</span>
                    <div className="preset-links">
                      <button type="button" className="text-link" onClick={() => setSelectedWeekdays(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday'])}>Mon–Fri</button>
                      <button type="button" className="text-link" onClick={() => setSelectedWeekdays(['Saturday', 'Sunday'])}>Sat–Sun</button>
                      <button type="button" className="text-link" onClick={() => setSelectedWeekdays(WEEKDAYS.map((w) => w.key))}>All</button>
                    </div>
                  </div>

                  <div className="weekday-chips" role="group" aria-label="Select weekdays">
                    {WEEKDAYS.map((w) => {
                      const isSelected = selectedWeekdays.includes(w.key)
                      return (
                        <button
                          key={w.key}
                          type="button"
                          className={`choice-chip ${isSelected ? 'selected' : ''}`}
                          aria-pressed={isSelected}
                          onClick={() => toggleWeekday(w.key)}
                        >
                          {w.short}
                        </button>
                      )
                    })}
                  </div>

                  <div className="two-fields">
                    <label className="field-label">
                      From
                      <input
                        type="time"
                        required
                        value={weeklyForm.start_time}
                        onChange={(e) => setWeeklyForm({ ...weeklyForm, start_time: e.target.value })}
                      />
                    </label>
                    <label className="field-label">
                      To
                      <input
                        type="time"
                        required
                        value={weeklyForm.end_time}
                        onChange={(e) => setWeeklyForm({ ...weeklyForm, end_time: e.target.value })}
                      />
                    </label>
                  </div>

                  {/* Preview of matching dates within 7-day horizon */}
                  <div className="weekly-preview-container">
                    <div className="weekly-preview-header">
                      <span className="preview-label">Matching dates preview:</span>
                      <span className="preview-summary-stat">
                        <strong>{willAddCount}</strong> to add · <strong>{alreadyExistsCount}</strong> existing
                      </span>
                    </div>

                    <div className="weekly-preview-list">
                      {weeklyPreview.length ? (
                        weeklyPreview.map((item) => (
                          <div key={item.date} className={`weekly-preview-item ${item.exists ? 'is-existing' : 'is-new'}`}>
                            <div className="preview-item-info">
                              <strong>{item.is_today ? 'Today' : item.day_name}</strong>
                              <span className="preview-date-sub">{item.short_date || item.date}</span>
                            </div>
                            {item.exists ? (
                              <span className="preview-badge duplicate" title="Window already configured">
                                Already exists
                              </span>
                            ) : (
                              <span className="preview-badge will-add">
                                Will add {weeklyForm.start_time}–{weeklyForm.end_time}
                              </span>
                            )}
                          </div>
                        ))
                      ) : (
                        <p className="empty-preview-note">No weekdays selected. Choose one or more weekdays above.</p>
                      )}
                    </div>
                  </div>

                  <button
                    className="button button-primary button-wide"
                    type="submit"
                    disabled={Boolean(busy) || selectedWeekdays.length === 0 || willAddCount === 0}
                  >
                    {busy === 'weekly-availability'
                      ? 'Creating windows…'
                      : willAddCount === 0
                        ? 'All selected windows already exist'
                        : `Add weekly availability (${willAddCount} ${willAddCount === 1 ? 'window' : 'windows'})`}
                  </button>
                </form>
              )}
              <form className="cutoff-row" onSubmit={handleEndOfDaySubmit}>
                <label className="field-label">End of day<input type="time" min="17:00" max="23:59" step="60" value={endOfDayDraft} onChange={(event) => setEndOfDayDraft(event.target.value)} /></label>
                <button className="button button-small button-quiet" type="submit" disabled={Boolean(busy) || endOfDayDraft === settings.end_of_day}>{busy === 'settings' ? 'Saving…' : 'Save cutoff'}</button>
              </form>
            </article>
          </section>

          <section className="panel task-list-panel">
            <div className="panel-heading">
              <div><p className="eyebrow">YOUR TASKS</p><h2>Task list</h2></div>
              <span className="subtle-pill">{tasks.length} total tasks</span>
            </div>
            {tasks.length ? <div className="task-list">{tasks.map((task) => (
              <div className="task-row" key={task.id}>
                <div className="task-main">
                  <span className="task-number">{String(task.id).padStart(2, '0')}</span>
                  <div>
                    <strong>{task.name}</strong>
                    <span>{task.duration} min · Difficulty {task.difficulty}/5 · Importance {task.importance}/5</span>
                  </div>
                </div>
                <div className="task-row-end">
                  {task.deadline ? <span className="deadline-tag">Due {task.deadline}</span> : null}
                  <button className="text-button danger-text" type="button" onClick={() => handleTaskDelete(task)} disabled={Boolean(busy)}>Remove</button>
                </div>
              </div>
            ))}</div> : <p className="empty-note">Your task list is empty.</p>}
          </section>

          <section className="panel timeline-panel">
            <div className="panel-heading">
              <div>
                <p className="eyebrow">{activeIsToday ? 'TODAY' : selectedDay.day_name?.toUpperCase()} · {activeDate} · CUTOFF {settings.end_of_day}</p>
                <h2>Planned chrono-schedule</h2>
              </div>
              <button className="button button-quiet" type="button" onClick={handleSchedule} disabled={Boolean(busy)}>
                {busy === 'schedule' ? 'Refreshing…' : 'Refresh plan'}
              </button>
            </div>
            <div className="timeline-summary">
              <span><i className="legend-dot task-dot" />{taskEntries.length} tasks</span>
              <span><i className="legend-dot break-dot" />{breakEntries.length} breaks</span>
              <span><i className="legend-dot unscheduled-dot" />{unscheduledEntries.length} unplaced</span>
            </div>
            {schedule.length ? (
              <div className="timeline-list">
                {schedule.map((entry, index) => (
                  <article className={`timeline-item ${entry.type} ${entry.duration >= 90 ? 'long-task' : ''}`} key={`${entry.type}-${entry.task}-${entry.start_time ?? index}`}>
                    <div className="timeline-time">
                      {entry.start_time ? (
                        <>
                          <strong>{entry.start_time}</strong>
                          <span>{entry.end_time}</span>
                        </>
                      ) : <span className="time-open">No slot</span>}
                    </div>
                    <span className="timeline-marker" aria-hidden="true" />
                    <div className="timeline-content">
                      <div className="timeline-title-row">
                        <div>
                          <span className="type-label">{entry.type === 'task' ? 'TASK' : entry.type === 'break' ? 'BREAK' : 'UNSCHEDULED'}</span>
                          <h3>{entry.task}</h3>
                        </div>
                        {entry.duration ? <span className="duration-tag">{formatMinutes(entry.duration)}</span> : null}
                      </div>
                      {entry.type === 'task' ? (
                        <div className="task-attributes">
                          <span>Difficulty {entry.difficulty}/5</span>
                          <span>Importance {entry.importance}/5</span>
                          {entry.predicted_success != null ? <span>Completion likelihood {Math.round(entry.predicted_success * 100)}%</span> : null}
                          {completionStatusFor(entry, feedback) ? <span>Feedback: {completionStatusFor(entry, feedback).replace('_', ' ')}</span> : null}
                        </div>
                      ) : null}
                      {Array.isArray(entry.reason) ? (
                        <p className="reason-text">{entry.reason.join(' · ')}</p>
                      ) : entry.reason ? (
                        <p className="reason-text">{entry.reason}</p>
                      ) : null}
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="empty-schedule">
                <span className="empty-orbit">＋</span>
                <strong>No tasks scheduled for {selectedDay.short_date || activeDate}</strong>
                <p>{availableMinutes > 0 ? `${formatMinutes(availableMinutes)} available capacity on this date.` : 'No availability configured on this date.'}</p>
                <button className="button button-primary" type="button" onClick={handleSchedule} disabled={Boolean(busy)}>Re-align 7-day schedule</button>
              </div>
            )}
          </section>

          <section className="content-grid insights-grid" id="insights">
            <article className="panel insight-panel">
              <div className="panel-heading">
                <div><p className="eyebrow">CURRENT SESSION</p><h2>What’s happening</h2></div>
                <span className="subtle-pill">Not historical</span>
              </div>
              <div className="insight-stats">
                <div><strong>{taskEntries.length}</strong><span>scheduled ({selectedDay.short_date || activeDate})</span></div>
                <div><strong>{breakEntries.length}</strong><span>breaks</span></div>
                <div><strong>{unscheduledEntries.length}</strong><span>unplaced</span></div>
              </div>
              <div className="completion-breakdown">
                <span>Completed <strong>{completedFeedback.length}</strong></span>
                <span>Partial <strong>{partialFeedback.length}</strong></span>
                <span>Skipped <strong>{skippedFeedback.length}</strong></span>
                <span>Avg. rated <strong>{averageRating}</strong></span>
              </div>
            </article>
            <article className="panel insight-panel">
              <div className="panel-heading">
                <div><p className="eyebrow">FEEDBACK LOOP</p><h2>Quick task check-in</h2></div>
                <span className="subtle-pill">10–15 sec</span>
              </div>
              <form className="feedback-form" onSubmit={handleFeedbackSubmit}>
                <label className="field-label">Task<select required value={feedbackForm.taskId} onChange={(event) => setFeedbackForm({ ...feedbackForm, taskId: event.target.value })}><option value="">Choose a task</option>{tasks.map((task) => <option key={task.id} value={task.id}>{task.name}</option>)}</select></label>
                {[
                  ['completion_status', 'How did it go?'],
                  ['difficulty_feedback', 'How did the difficulty feel?'],
                  ['timing_feedback', 'How was the timing?'],
                  ['energy_impact', 'Energy impact · optional'],
                ].map(([field, label]) => (
                  <fieldset className="feedback-group" key={field}>
                    <legend>{label}</legend>
                    <div className="choice-row">
                      {feedbackChoices[field].map(([value, text]) => (
                        <button className={`choice-chip ${feedbackForm[field] === value ? 'selected' : ''}`} type="button" key={value} aria-pressed={feedbackForm[field] === value} onClick={() => setFeedbackForm({ ...feedbackForm, [field]: feedbackForm[field] === value ? '' : value })}>{text}</button>
                      ))}
                    </div>
                  </fieldset>
                ))}
                <div className="feedback-footer">
                  <span>{feedback.length ? `${feedback.length} saved in this backend session` : 'Answers are stored for this backend session.'}</span>
                  <button className="button button-primary" type="submit" disabled={Boolean(busy) || !tasks.length}>{busy === 'feedback' ? 'Saving…' : 'Save check-in'}</button>
                </div>
              </form>
            </article>
          </section>
          <p className="model-note">Feedback is stored with task features. The current logistic model uses energy, difficulty, duration, and the completed/not-completed signal; newer categorical answers are saved but are not yet model inputs.</p>
        </main>
      ) : (
        /* CALENDAR VIEW */
        <main className="dashboard calendar-dashboard" id="calendar">
          <section className="page-heading">
            <div>
              <p className="eyebrow">SEVEN-DAY TIME GRID</p>
              <h1>Weekly calendar</h1>
              <p className="heading-copy">
                {horizonDays[0]?.date} to {horizonDays[6]?.date} · Drag tasks into available slots or select a task to reschedule.
              </p>
            </div>
            <div className="calendar-actions">
              <div className="live-status"><span className="status-dot" />{statusMessage}</div>
              <button className="button button-quiet" type="button" onClick={handleSchedule} disabled={Boolean(busy)}>
                {busy === 'schedule' ? 'Refreshing…' : 'Refresh plan'}
              </button>
            </div>
          </section>
          {error ? <div className="error-banner" role="alert">{error}</div> : null}

          <div className="calendar-layout">
            {/* Main Time-Grid */}
            <div className="calendar-grid-container">
              <div className="calendar-scroll-wrapper">
                <div className="calendar-grid">
                  {/* Top-left corner cell */}
                  <div className="calendar-corner-cell">
                    <span className="corner-label">Time</span>
                  </div>

                  {/* 7 Day Column Headers */}
                  {horizonDays.map((day) => (
                    <div key={`header-${day.date}`} className={`calendar-day-header ${day.is_today ? 'is-today' : ''}`}>
                      <span className="cal-day-name">{day.is_today ? 'Today' : day.day_name.slice(0, 3)}</span>
                      <strong className="cal-day-date">{day.short_date || day.date}</strong>
                      <span className="cal-day-stat">
                        {formatMinutes(day.scheduled_minutes)} / {formatMinutes(day.available_minutes)}
                      </span>
                    </div>
                  ))}

                  {/* Vertical Time Axis */}
                  <div className="calendar-time-axis" style={{ height: `${GRID_HEIGHT}px` }}>
                    {GRID_HOURS.map((hour) => (
                      <div key={hour} className="time-axis-label" style={{ top: `${(hour - GRID_START_HOUR) * 60 * PIXELS_PER_MINUTE}px` }}>
                        <span>{String(hour).padStart(2, '0')}:00</span>
                      </div>
                    ))}
                  </div>

                  {/* 7 Day Tracks */}
                  {horizonDays.map((day) => {
                    const dayAvail = availability.filter((w) => w.date === day.date)
                    const dayTasks = (day.schedule || []).filter((e) => e.type === 'task')
                    const dayBreaks = (day.schedule || []).filter((e) => e.type === 'break')

                    return (
                      <div
                        key={`track-${day.date}`}
                        className={`calendar-day-track ${day.is_today ? 'track-today' : ''} ${dragOverDate === day.date ? 'drag-over' : ''}`}
                        style={{ height: `${GRID_HEIGHT}px` }}
                        onDragOver={(e) => handleDragOver(e, day.date)}
                        onDragLeave={handleDragLeave}
                        onDrop={(e) => handleDrop(e, day.date)}
                      >
                        {/* Hour horizontal grid lines */}
                        {GRID_HOURS.map((hour) => (
                          <div
                            key={hour}
                            className="calendar-hour-line"
                            style={{ top: `${(hour - GRID_START_HOUR) * 60 * PIXELS_PER_MINUTE}px` }}
                          />
                        ))}

                        {/* Cutoff line */}
                        {cutoffTop >= 0 && cutoffTop <= GRID_HEIGHT ? (
                          <div className="calendar-cutoff-line" style={{ top: `${cutoffTop}px` }}>
                            <span className="cutoff-tag">Cutoff {settings.end_of_day}</span>
                          </div>
                        ) : null}

                        {/* Availability windows */}
                        {dayAvail.map((win, idx) => {
                          const sMin = timeToMinutes(win.start_time)
                          const eMin = Math.min(timeToMinutes(win.end_time), cutoffMinutes)
                          if (eMin <= sMin) return null
                          const top = (sMin - GRID_START_HOUR * 60) * PIXELS_PER_MINUTE
                          const height = (eMin - sMin) * PIXELS_PER_MINUTE
                          return (
                            <div
                              key={`avail-${win.start_time}-${win.end_time}-${idx}`}
                              className="calendar-avail-block"
                              style={{ top: `${Math.max(0, top)}px`, height: `${Math.max(0, height)}px` }}
                              title={`Available ${win.start_time} - ${win.end_time}`}
                            >
                              <span className="avail-label">Available {win.start_time}–{win.end_time}</span>
                            </div>
                          )
                        })}

                        {/* Breaks */}
                        {dayBreaks.map((b, idx) => {
                          const bStart = timeToMinutes(b.start_time)
                          const bDur = b.duration || 15
                          const top = (bStart - GRID_START_HOUR * 60) * PIXELS_PER_MINUTE
                          const height = bDur * PIXELS_PER_MINUTE
                          return (
                            <div
                              key={`break-${b.start_time}-${idx}`}
                              className="calendar-break-block"
                              style={{ top: `${Math.max(0, top)}px`, height: `${Math.max(0, height)}px` }}
                              title={`Break ${b.start_time} - ${b.end_time}`}
                            >
                              <span>☕ Break ({bDur}m)</span>
                            </div>
                          )
                        })}

                        {/* Scheduled Task blocks */}
                        {dayTasks.map((task) => {
                          const tStart = task.start_minute != null ? task.start_minute : timeToMinutes(task.start_time)
                          const tDur = task.duration
                          const top = (tStart - GRID_START_HOUR * 60) * PIXELS_PER_MINUTE
                          const height = Math.max(34, tDur * PIXELS_PER_MINUTE)
                          const isSelected = selectedTaskDetails?.task_id === task.task_id

                          return (
                            <div
                              key={task.task_id || task.task}
                              className={`calendar-task-block ${isSelected ? 'selected' : ''}`}
                              style={{ top: `${Math.max(0, top)}px`, height: `${height}px` }}
                              draggable={!busy}
                              onDragStart={(e) => handleDragStart(e, task, day.date)}
                              onClick={() => openTaskDetails(task, day.date)}
                              role="button"
                              tabIndex={0}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter' || e.key === ' ') {
                                  openTaskDetails(task, day.date)
                                }
                              }}
                            >
                              <div className="task-block-header">
                                <span className="task-block-time">{task.start_time}–{task.end_time}</span>
                                <span className="task-block-dur">{task.duration}m</span>
                              </div>
                              <strong className="task-block-name">{task.task}</strong>
                              <div className="task-block-tags">
                                {task.difficulty ? <span>Diff {task.difficulty}/5</span> : null}
                                {task.deadline ? <span className="task-due-tag">Due {task.deadline}</span> : null}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    )
                  })}
                </div>
              </div>
            </div>

            {/* Sidebar: Unscheduled Tasks & Task Details */}
            <aside className="calendar-sidebar">
              {/* Task Details / Reschedule Panel (When a task is selected) */}
              {selectedTaskDetails ? (
                <div className="panel task-details-panel">
                  <div className="panel-heading">
                    <div>
                      <p className="eyebrow">TASK DETAILS</p>
                      <h2>{selectedTaskDetails.task || selectedTaskDetails.name}</h2>
                    </div>
                    <button
                      className="icon-button"
                      type="button"
                      aria-label="Close details"
                      onClick={() => setSelectedTaskDetails(null)}
                    >
                      ×
                    </button>
                  </div>

                  <div className="details-grid">
                    <div><span>Duration</span><strong>{formatMinutes(selectedTaskDetails.duration)}</strong></div>
                    <div><span>Difficulty</span><strong>{selectedTaskDetails.difficulty}/5</strong></div>
                    <div><span>Importance</span><strong>{selectedTaskDetails.importance}/5</strong></div>
                    <div><span>Deadline</span><strong>{selectedTaskDetails.deadline || 'None'}</strong></div>
                    <div><span>Scheduled Date</span><strong>{selectedTaskDetails.date || 'Unscheduled'}</strong></div>
                    <div><span>Scheduled Time</span><strong>{selectedTaskDetails.start_time ? `${selectedTaskDetails.start_time} – ${selectedTaskDetails.end_time}` : 'No slot'}</strong></div>
                  </div>

                  {selectedTaskDetails.reason ? (
                    <div className="details-reason">
                      <span>Status / Reason:</span>
                      <p className="reason-text">
                        {Array.isArray(selectedTaskDetails.reason)
                          ? selectedTaskDetails.reason.join(' · ')
                          : selectedTaskDetails.reason}
                      </p>
                    </div>
                  ) : null}

                  {/* Explicit Reschedule Form */}
                  <form className="reschedule-form" onSubmit={handleExplicitReschedule}>
                    <span className="reschedule-form-title">Explicit Reschedule Action</span>
                    <label className="field-label">
                      Target Date
                      <select
                        value={rescheduleForm.date}
                        onChange={(e) => setRescheduleForm({ ...rescheduleForm, date: e.target.value })}
                        required
                      >
                        {horizonDays.map((d) => (
                          <option key={d.date} value={d.date}>
                            {d.is_today ? 'Today' : d.day_name} ({d.short_date || d.date})
                          </option>
                        ))}
                      </select>
                    </label>
                    <label className="field-label">
                      Start Time (15-min snap)
                      <input
                        type="time"
                        step="900"
                        value={rescheduleForm.start_time}
                        onChange={(e) => setRescheduleForm({ ...rescheduleForm, start_time: e.target.value })}
                        required
                      />
                    </label>
                    <button
                      className="button button-primary button-wide"
                      type="submit"
                      disabled={Boolean(busy)}
                    >
                      {busy === 'reschedule' ? 'Validating move…' : 'Reschedule Task'}
                    </button>
                  </form>
                </div>
              ) : null}

              {/* Dedicated Unscheduled Tasks Panel */}
              <div className="panel unscheduled-panel">
                <div className="panel-heading">
                  <div>
                    <p className="eyebrow">UNSCHEDULED</p>
                    <h2>Unplaced tasks</h2>
                  </div>
                  <span className="subtle-pill">{unscheduledTasksList.length} total</span>
                </div>
                <p className="unscheduled-sidebar-desc">
                  Drag any task into an available column or click to open explicit reschedule.
                </p>

                <div className="unscheduled-scroll-list">
                  {unscheduledTasksList.length ? (
                    unscheduledTasksList.map((item) => {
                      const isSelected = selectedTaskDetails?.task_id === item.task_id
                      return (
                        <article
                          key={item.task_id || item.task}
                          className={`unscheduled-card ${isSelected ? 'selected' : ''}`}
                          draggable={!busy}
                          onDragStart={(e) => handleDragStart(e, item, null)}
                          onClick={() => openTaskDetails(item, null)}
                          role="button"
                          tabIndex={0}
                          onKeyDown={(e) => {
                            if (e.key === 'Enter' || e.key === ' ') {
                              openTaskDetails(item, null)
                            }
                          }}
                        >
                          <div className="unscheduled-card-head">
                            <strong>{item.task}</strong>
                            <span className="duration-tag">{formatMinutes(item.duration)}</span>
                          </div>
                          <div className="unscheduled-card-meta">
                            <span>Diff {item.difficulty}/5</span>
                            <span>Imp {item.importance}/5</span>
                            {item.deadline ? <span className="deadline-tag">Due {item.deadline}</span> : null}
                          </div>
                          <p className="reason-text">{item.reason || 'No suitable slot found within the 7-day planning horizon.'}</p>
                          <button
                            className="button button-small button-quiet"
                            type="button"
                            onClick={(e) => {
                              e.stopPropagation()
                              openTaskDetails(item, null)
                            }}
                          >
                            Reschedule…
                          </button>
                        </article>
                      )
                    })
                  ) : (
                    <div className="empty-unscheduled-note">
                      <span className="fit-good">✓ All tasks scheduled</span>
                      <p>Every task in your list has a confirmed slot within the 7-day horizon.</p>
                    </div>
                  )}
                </div>
              </div>
            </aside>
          </div>
        </main>
      )}

      <footer className="page-footer">
        <span>DAYPLAN · 7-DAY CHRONO-PLANNER</span>
        <span>Planning horizon: {horizonDays[0]?.date} to {horizonDays[6]?.date} (exactly 7 calendar dates)</span>
        <span>End of day {settings.end_of_day}</span>
      </footer>
    </div>
  )
}

export default App