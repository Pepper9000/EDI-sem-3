export function computeProductivityInsights(feedbackList = []) {
  const totalOutcomes = feedbackList.length

  if (totalOutcomes === 0) {
    return {
      total_outcomes: 0,
      completed_count: 0,
      completion_rate: null,
      on_time_recorded_count: 0,
      on_time_count: 0,
      on_time_rate: null,
      rating_recorded_count: 0,
      average_rating: null,
      duration_metrics: {
        sample_size: 0,
        avg_planned_duration: null,
        avg_actual_duration: null,
        duration_diff_minutes: null,
      },
      compatibility_comparison: {
        matched: { sample_size: 0, completed_count: 0, completion_rate: null },
        mismatched: { sample_size: 0, completed_count: 0, completion_rate: null },
      },
      by_energy: [],
      by_difficulty: [],
      data_status: 'no_data',
      sample_size_adequate: false,
      summary: 'No task outcomes recorded yet. Complete check-ins to view productivity insights.',
      cautionary_note: 'Observational correlation does not establish causation. Task outcomes depend on interruptions, personal pacing, and estimation error as well as scheduling.',
    }
  }

  const completedRecords = feedbackList.filter(
    (f) => f.completion_status === 'completed' || (f.completion_status == null && f.completed)
  )
  const completedCount = completedRecords.length
  const completionRate = Number(((completedCount / totalOutcomes) * 100).toFixed(1))

  const onTimeRecords = feedbackList.filter((f) => f.on_time !== null && f.on_time !== undefined)
  const onTimeRecordedCount = onTimeRecords.length
  const onTimeCount = onTimeRecords.filter((f) => f.on_time === true).length
  const onTimeRate = onTimeRecordedCount > 0
    ? Number(((onTimeCount / onTimeRecordedCount) * 100).toFixed(1))
    : null

  const ratedRecords = feedbackList.filter((f) => f.rating !== null && f.rating !== undefined && Number.isFinite(f.rating))
  const ratingRecordedCount = ratedRecords.length
  const averageRating = ratingRecordedCount > 0
    ? Number((ratedRecords.reduce((sum, f) => sum + f.rating, 0) / ratingRecordedCount).toFixed(1))
    : null

  // Strictly where actual_duration was genuinely supplied
  const actualDurRecords = feedbackList.filter(
    (f) => f.actual_duration !== null && f.actual_duration !== undefined && f.actual_duration > 0
  )
  const durSample = actualDurRecords.length
  let durationMetrics = {
    sample_size: 0,
    avg_planned_duration: null,
    avg_actual_duration: null,
    duration_diff_minutes: null,
  }
  if (durSample > 0) {
    const avgPlanned = Number((actualDurRecords.reduce((sum, f) => sum + f.duration, 0) / durSample).toFixed(1))
    const avgActual = Number((actualDurRecords.reduce((sum, f) => sum + f.actual_duration, 0) / durSample).toFixed(1))
    durationMetrics = {
      sample_size: durSample,
      avg_planned_duration: avgPlanned,
      avg_actual_duration: avgActual,
      duration_diff_minutes: Number((avgActual - avgPlanned).toFixed(1)),
    }
  }

  const calcGroup = (records) => {
    const count = records.length
    if (count === 0) return { sample_size: 0, completed_count: 0, completion_rate: null }
    const comp = records.filter(
      (f) => f.completion_status === 'completed' || (f.completion_status == null && f.completed)
    ).length
    return {
      sample_size: count,
      completed_count: comp,
      completion_rate: Number(((comp / count) * 100).toFixed(1)),
    }
  }

  const matchedRecords = feedbackList.filter((f) => Math.abs(f.difficulty - f.energy) <= 1)
  const mismatchedRecords = feedbackList.filter((f) => Math.abs(f.difficulty - f.energy) > 1)

  const compatibilityComparison = {
    matched: calcGroup(matchedRecords),
    mismatched: calcGroup(mismatchedRecords),
  }

  const byEnergy = []
  for (let level = 1; level <= 5; level += 1) {
    const records = feedbackList.filter((f) => f.energy === level)
    if (records.length > 0) {
      const res = calcGroup(records)
      res.energy = level
      byEnergy.push(res)
    }
  }

  const byDifficulty = []
  for (let diff = 1; diff <= 5; diff += 1) {
    const records = feedbackList.filter((f) => f.difficulty === diff)
    if (records.length > 0) {
      const res = calcGroup(records)
      res.difficulty = diff
      byDifficulty.push(res)
    }
  }

  const sampleSizeAdequate = totalOutcomes >= 5
  let dataStatus = 'insufficient_sample'
  let summary = ''
  if (totalOutcomes < 5) {
    dataStatus = 'insufficient_sample'
    summary = `Preliminary data: ${totalOutcomes} task outcome(s) recorded. A minimum sample size of 5 check-ins is recommended before assessing whether energy-aware placement correlates with completion.`
  } else {
    dataStatus = 'sufficient_sample'
    const matchedStat = compatibilityComparison.matched
    const mismatchedStat = compatibilityComparison.mismatched
    if (matchedStat.sample_size > 0 && mismatchedStat.sample_size > 0) {
      summary = `Observed ${totalOutcomes} outcomes: energy-matched tasks had a ${matchedStat.completion_rate}% completion rate (N=${matchedStat.sample_size}) vs ${mismatchedStat.completion_rate}% for mismatched tasks (N=${mismatchedStat.sample_size}).`
    } else {
      summary = `Observed outcomes across ${totalOutcomes} task check-in(s).`
    }
  }

  return {
    total_outcomes: totalOutcomes,
    completed_count: completedCount,
    completion_rate: completionRate,
    on_time_recorded_count: onTimeRecordedCount,
    on_time_count: onTimeCount,
    on_time_rate: onTimeRate,
    rating_recorded_count: ratingRecordedCount,
    average_rating: averageRating,
    duration_metrics: durationMetrics,
    compatibility_comparison: compatibilityComparison,
    by_energy: byEnergy,
    by_difficulty: byDifficulty,
    data_status: dataStatus,
    sample_size_adequate: sampleSizeAdequate,
    summary,
    cautionary_note: 'Observational correlation does not establish causation. Task outcomes depend on interruptions, personal pacing, and estimation error as well as scheduling.',
  }
}
