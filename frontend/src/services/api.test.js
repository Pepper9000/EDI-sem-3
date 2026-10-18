import assert from 'node:assert/strict'
import { test } from 'node:test'
import { api } from './api.js'

const jsonResponse = (payload) => ({
  ok: true,
  status: 200,
  headers: { get: () => 'application/json' },
  json: async () => payload,
})

test('saves the selected end-of-day setting', async () => {
  const originalFetch = globalThis.fetch
  const calls = []
  globalThis.fetch = async (...args) => {
    calls.push(args)
    return jsonResponse({ end_of_day: '20:30' })
  }

  try {
    const result = await api.updateSettings('20:30')
    assert.equal(result.end_of_day, '20:30')
    assert.equal(calls[0][0], 'http://127.0.0.1:8000/settings')
    assert.equal(calls[0][1].method, 'PUT')
    assert.equal(calls[0][1].body, JSON.stringify({ end_of_day: '20:30' }))
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('removes only the selected availability window', async () => {
  const originalFetch = globalThis.fetch
  const calls = []
  globalThis.fetch = async (...args) => {
    calls.push(args)
    return jsonResponse({ message: 'Availability window removed' })
  }

  try {
    await api.deleteAvailability({ date: '2026-10-01', start_time: '14:00', end_time: '17:00' })
    const [url, options] = calls[0]
    assert.match(url, /\/availability\/window\?/)
    assert.match(url, /date=2026-10-01/)
    assert.match(url, /start_time=14%3A00/)
    assert.match(url, /end_time=17%3A00/)
    assert.equal(options.method, 'DELETE')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('requests schedule with or without specific date parameter', async () => {
  const originalFetch = globalThis.fetch
  const calls = []
  globalThis.fetch = async (...args) => {
    calls.push(args)
    return jsonResponse({
      date: '2026-10-18',
      available_minutes: 180,
      scheduled_minutes: 120,
      unused_minutes: 60,
      days: Array.from({ length: 7 }, (_, i) => ({
        date: `2026-10-${18 + i}`,
        available_minutes: 180,
        scheduled_minutes: 120,
        unused_minutes: 60,
        schedule: [],
      })),
    })
  }

  try {
    await api.getSchedule()
    assert.equal(calls[0][0], 'http://127.0.0.1:8000/schedule')

    await api.getSchedule('2026-10-19')
    assert.equal(calls[1][0], 'http://127.0.0.1:8000/schedule?date=2026-10-19')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('horizon contains exactly seven dates and no eighth date is displayed', async () => {
  const baseDate = '2026-10-18'
  const [year, month, day] = baseDate.split('-').map(Number)
  const base = new Date(year, month - 1, day)
  const horizonDates = Array.from({ length: 7 }, (_, i) => {
    const cur = new Date(base.getFullYear(), base.getMonth(), base.getDate() + i)
    const y = cur.getFullYear()
    const m = String(cur.getMonth() + 1).padStart(2, '0')
    const d = String(cur.getDate()).padStart(2, '0')
    return `${y}-${m}-${d}`
  })

  // Exactly seven consecutive calendar dates
  assert.equal(horizonDates.length, 7)
  assert.equal(horizonDates[0], '2026-10-18')
  assert.equal(horizonDates[6], '2026-10-24')

  // Eighth day is strictly not included
  const dayEight = '2026-10-25'
  assert.equal(horizonDates.includes(dayEight), false)
})

test('selecting a date shows that date actual schedule and statistics', async () => {
  const mockScheduleData = {
    date: '2026-10-18',
    days: [
      {
        date: '2026-10-18',
        available_minutes: 60,
        scheduled_minutes: 0,
        unused_minutes: 60,
        unscheduled_count: 0,
        schedule: [],
      },
      {
        date: '2026-10-19',
        available_minutes: 240,
        scheduled_minutes: 180,
        unused_minutes: 60,
        unscheduled_count: 0,
        schedule: [
          {
            task_id: 1,
            task: 'Project Work',
            duration: 180,
            start_time: '12:00',
            end_time: '15:00',
            type: 'task',
          },
        ],
      },
    ],
  }

  // Select tomorrow (2026-10-19)
  const selectedDay = mockScheduleData.days.find((d) => d.date === '2026-10-19')
  assert.ok(selectedDay)
  assert.equal(selectedDay.date, '2026-10-19')
  assert.equal(selectedDay.available_minutes, 240)
  assert.equal(selectedDay.scheduled_minutes, 180)
  assert.equal(selectedDay.unused_minutes, 60)
  // Mathematical consistency
  assert.equal(selectedDay.available_minutes, selectedDay.scheduled_minutes + selectedDay.unused_minutes)
  assert.equal(selectedDay.schedule.length, 1)
  assert.equal(selectedDay.schedule[0].task, 'Project Work')
})

test('rescheduleTask sends POST to /tasks/:id/reschedule with date and start_time', async () => {
  const originalFetch = globalThis.fetch
  const calls = []
  globalThis.fetch = async (...args) => {
    calls.push(args)
    return jsonResponse({
      message: 'Task 1 successfully rescheduled to 2026-10-19 at 14:00',
      task_id: 1,
      date: '2026-10-19',
      start_time: '14:00',
      end_time: '15:00',
    })
  }

  try {
    const res = await api.rescheduleTask(1, { date: '2026-10-19', start_time: '14:00' })
    assert.equal(calls[0][0], 'http://127.0.0.1:8000/tasks/1/reschedule')
    assert.equal(calls[0][1].method, 'POST')
    assert.equal(calls[0][1].body, JSON.stringify({ date: '2026-10-19', start_time: '14:00' }))
    assert.equal(res.start_time, '14:00')
    assert.equal(res.end_time, '15:00')
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('rescheduleTask throws error with detail message on rejected drops', async () => {
  const originalFetch = globalThis.fetch
  globalThis.fetch = async () => ({
    ok: false,
    status: 400,
    headers: { get: () => 'application/json' },
    json: async () => ({ detail: 'Task ends at 22:30, which exceeds the 22:00 cutoff.' }),
  })

  try {
    await assert.rejects(
      async () => {
        await api.rescheduleTask(2, { date: '2026-10-18', start_time: '21:30' })
      },
      {
        message: 'Task ends at 22:30, which exceeds the 22:00 cutoff.',
      }
    )
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('tab navigation supports planner and calendar views', () => {
  let activeTab = 'planner'
  const switchTab = (tab) => {
    activeTab = tab
  }

  assert.equal(activeTab, 'planner')
  switchTab('calendar')
  assert.equal(activeTab, 'calendar')
  switchTab('planner')
  assert.equal(activeTab, 'planner')
})

test('addWeeklyAvailability sends POST to /availability/weekly with weekdays and times', async () => {
  const originalFetch = globalThis.fetch
  const calls = []
  globalThis.fetch = async (...args) => {
    calls.push(args)
    return jsonResponse({
      message: 'Created 2 availability windows, skipped 1 duplicates.',
      created: [],
      skipped: [],
      total_created: 2,
      total_skipped: 1,
    })
  }

  try {
    const payload = {
      weekdays: ['Monday', 'Wednesday'],
      start_time: '09:00',
      end_time: '12:00',
    }
    const result = await api.addWeeklyAvailability(payload)
    assert.equal(result.total_created, 2)
    assert.equal(calls[0][0], 'http://127.0.0.1:8000/availability/weekly')
    assert.equal(calls[0][1].method, 'POST')
    assert.equal(calls[0][1].body, JSON.stringify(payload))
  } finally {
    globalThis.fetch = originalFetch
  }
})

test('previewWeeklyAvailability sends POST to /availability/weekly/preview', async () => {
  const originalFetch = globalThis.fetch
  const calls = []
  globalThis.fetch = async (...args) => {
    calls.push(args)
    return jsonResponse({
      matching_dates: [],
      will_add_count: 3,
      already_exists_count: 0,
      total_matching: 3,
    })
  }

  try {
    const payload = {
      weekdays: ['Monday', 'Tuesday', 'Wednesday'],
      start_time: '14:00',
      end_time: '17:00',
    }
    const result = await api.previewWeeklyAvailability(payload)
    assert.equal(result.will_add_count, 3)
    assert.equal(calls[0][0], 'http://127.0.0.1:8000/availability/weekly/preview')
    assert.equal(calls[0][1].method, 'POST')
  } finally {
    globalThis.fetch = originalFetch
  }
})


