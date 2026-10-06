import type { CallRecord, DashboardFilters, KpiSummary } from "../types";

export function filterCalls(calls: CallRecord[], filters: DashboardFilters, disposition?: string): CallRecord[] {
  const now = Date.now();
  const days = filters.range === "7D" ? 7 : filters.range === "30D" ? 30 : filters.range === "60D" ? 60 : 0;
  const threshold = days ? now - days * 86_400_000 : 0;
  return calls.filter((call) => {
    if (threshold && new Date(call.startedAt).getTime() < threshold) return false;
    if (filters.campaign !== "ALL" && call.campaignId !== filters.campaign) return false;
    if (filters.language !== "ALL" && call.language !== filters.language) return false;
    if (filters.region !== "ALL" && call.region !== filters.region) return false;
    if (disposition && call.disposition !== disposition) return false;
    return true;
  });
}

export function summarizeCalls(calls: CallRecord[]): KpiSummary {
  const completed = calls.filter((call) => call.status === "COMPLETED");
  const connected = calls.filter((call) => call.connected);
  const totalCost = calls.reduce((sum, call) => sum + call.costInr, 0);
  return {
    callsDialed: calls.length,
    connected: connected.length,
    answerRate: calls.length ? connected.length / calls.length : 0,
    closed: calls.filter((call) => call.disposition === "CLOSED").length,
    callbacks: calls.filter((call) => call.disposition === "CALLBACK_SCHEDULED").length,
    escalated: calls.filter((call) => call.disposition === "ESCALATED").length,
    refusedDnd: calls.filter((call) => call.disposition === "NOT_INTERESTED" || call.disposition === "DND").length,
    averageDurationSec: completed.length ? completed.reduce((sum, call) => sum + call.durationSec, 0) / completed.length : 0,
    averageSentiment: connected.length ? connected.reduce((sum, call) => sum + call.sentiment, 0) / connected.length : 0,
    costPerCallInr: calls.length ? totalCost / calls.length : 0,
    costPerResolvedInr: calls.some((call) => call.disposition === "CLOSED") ? totalCost / calls.filter((call) => call.disposition === "CLOSED").length : 0,
  };
}

export function previousPeriodCalls(calls: CallRecord[], filters: DashboardFilters): CallRecord[] {
  if (filters.range === "ALL") return [];
  const days = filters.range === "7D" ? 7 : filters.range === "30D" ? 30 : 60;
  const now = Date.now();
  const start = now - days * 2 * 86_400_000;
  const end = now - days * 86_400_000;
  return calls.filter((call) => {
    const time = new Date(call.startedAt).getTime();
    return time >= start && time < end
      && (filters.campaign === "ALL" || call.campaignId === filters.campaign)
      && (filters.language === "ALL" || call.language === filters.language)
      && (filters.region === "ALL" || call.region === filters.region);
  });
}

export function formatDuration(seconds: number): string {
  const minutes = Math.floor(seconds / 60);
  const remaining = Math.round(seconds % 60);
  return `${minutes}m ${String(remaining).padStart(2, "0")}s`;
}

export function formatInr(amount: number): string {
  return new Intl.NumberFormat("en-IN", { style: "currency", currency: "INR", maximumFractionDigits: 0 }).format(amount);
}

export function formatDateTime(value: string): string {
  return new Intl.DateTimeFormat("en-IN", { dateStyle: "medium", timeStyle: "short", timeZone: "Asia/Kolkata" }).format(new Date(value));
}

export function formatIstDateTimeInput(value: string): string {
  const fields = new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" }).formatToParts(new Date(value));
  const part = (name: string) => fields.find((item) => item.type === name)?.value ?? "00";
  return `${part("year")}-${part("month")}-${part("day")}T${part("hour")}:${part("minute")}`;
}

export function istDateTimeInputToIso(value: string): string {
  return new Date(`${value}:00+05:30`).toISOString();
}

export function isTodayIst(value: string | null): boolean {
  if (!value) return false;
  const format = (date: Date) => new Intl.DateTimeFormat("en-CA", { timeZone: "Asia/Kolkata", year: "numeric", month: "2-digit", day: "2-digit" }).format(date);
  return format(new Date(value)) === format(new Date());
}

export function formatDate(value: string): string {
  return new Intl.DateTimeFormat("en-IN", { day: "2-digit", month: "short", timeZone: "Asia/Kolkata" }).format(new Date(value));
}
