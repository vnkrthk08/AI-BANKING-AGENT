import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CallRecord } from "../types";
import { formatDate } from "../services/selectors";

const OUTCOME_COLORS: Record<string, string> = { CLOSED: "#27805f", CALLBACK_SCHEDULED: "#d29132", ESCALATED: "#b74747", NOT_INTERESTED: "#8793a4", BUSY: "#d3b461", NO_ANSWER: "#aab3c0", DND: "#556276", FAILED: "#c6cbd3" };
const TEXT = "#657287";
const GRID = "#e9edf2";

export function DrillChart({ children, onDrill, label = "Open filtered call log" }: { children: React.ReactNode; onDrill: () => void; label?: string }) {
  return <div className="ops-chart-drill" role="link" tabIndex={0} aria-label={label} onClick={onDrill} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onDrill(); } }}>{children}</div>;
}

export function OutcomeDonut({ calls }: { calls: CallRecord[] }) {
  const values = new Map<string, number>();
  calls.forEach((call) => { if (call.disposition) values.set(call.disposition, (values.get(call.disposition) ?? 0) + 1); });
  const data = [...values].map(([name, value]) => ({ name: name.replaceAll("_", " "), value, key: name }));
  return <ResponsiveContainer width="100%" height={226}><PieChart><Pie data={data} dataKey="value" nameKey="name" innerRadius={61} outerRadius={88} paddingAngle={2} stroke="none">{data.map((item) => <Cell key={item.key} fill={OUTCOME_COLORS[item.key] ?? "#7f8b9e"} />)}</Pie><Tooltip formatter={(value) => [Number(value ?? 0).toLocaleString("en-IN"), "Calls"]} contentStyle={{ border: "1px solid #dfe5eb", borderRadius: 8, fontSize: 12 }} /><text x="50%" y="47%" textAnchor="middle" fill="#344257" fontSize="23" fontWeight="700">{calls.length.toLocaleString("en-IN")}</text><text x="50%" y="59%" textAnchor="middle" fill={TEXT} fontSize="10">calls in view</text></PieChart></ResponsiveContainer>;
}

export function OutcomeFunnel({ calls }: { calls: CallRecord[] }) {
  const dialed = calls.length;
  const connected = calls.filter((call) => call.connected).length;
  const consented = calls.filter((call) => call.connected && call.consented).length;
  const completed = calls.filter((call) => call.connected && call.consented && call.status === "COMPLETED").length;
  const closed = calls.filter((call) => call.disposition === "CLOSED").length;
  const stages = [{ label: "Dialed", count: dialed }, { label: "Connected", count: connected }, { label: "Consented", count: consented }, { label: "Completed", count: completed }, { label: "Closed", count: closed }];
  return <div className="ops-funnel">{stages.map((stage, index) => {
    const drop = index ? (1 - stage.count / Math.max(1, stages[index - 1]!.count)) * 100 : 0;
    const width = Math.max(28, 100 - index * 15);
    return <div className="ops-funnel-stage" key={stage.label}><div className="ops-funnel-track"><div className={`ops-funnel-bar funnel-${index}`} style={{ width: `${width}%` }}><span>{stage.label}</span><strong>{stage.count.toLocaleString("en-IN")}</strong></div></div>{index > 0 && <span className="ops-funnel-drop">{drop.toFixed(1)}% drop</span>}</div>;
  })}</div>;
}

export function DailyTrend({ calls }: { calls: CallRecord[] }) {
  const now = new Date();
  const data = Array.from({ length: 14 }, (_, index) => {
    const date = new Date(now.getTime() - (13 - index) * 86_400_000);
    const key = date.toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" });
    const today = calls.filter((call) => new Date(call.startedAt).toLocaleDateString("en-CA", { timeZone: "Asia/Kolkata" }) === key);
    return { day: formatDate(date.toISOString()), calls: today.length, closed: today.filter((call) => call.disposition === "CLOSED").length };
  });
  return <ResponsiveContainer width="100%" height={238}><LineChart data={data} margin={{ top: 12, right: 14, left: -16, bottom: 0 }}><CartesianGrid stroke={GRID} vertical={false} /><XAxis dataKey="day" tick={{ fill: TEXT, fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis tick={{ fill: TEXT, fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip contentStyle={{ border: "1px solid #dfe5eb", borderRadius: 8, fontSize: 12 }} /><Line type="monotone" dataKey="calls" name="Calls dialed" stroke="#087e83" strokeWidth={2.5} dot={false} activeDot={{ r: 4 }} /><Line type="monotone" dataKey="closed" name="Closed" stroke="#5a7baa" strokeWidth={2} dot={false} activeDot={{ r: 4 }} /></LineChart></ResponsiveContainer>;
}

export function HourlyHeatmap({ calls }: { calls: CallRecord[] }) {
  const hours = Array.from({ length: 12 }, (_, index) => index + 9);
  const days = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];
  const totals = calls.map((call) => {
    const date = new Date(call.startedAt);
    const parts = new Intl.DateTimeFormat("en-US", { timeZone: "Asia/Kolkata", weekday: "short", hour: "numeric", hour12: false }).formatToParts(date);
    return { day: parts.find((part) => part.type === "weekday")?.value ?? "Mon", hour: Number(parts.find((part) => part.type === "hour")?.value ?? 9) };
  });
  const peak = Math.max(1, ...days.flatMap((day) => hours.map((hour) => totals.filter((item) => item.day === day && item.hour === hour).length)));
  return <div className="ops-heatmap"><div className="ops-heatmap-label" /><div className="ops-heatmap-hours">{hours.map((hour) => <span key={hour}>{hour % 3 === 0 ? `${hour}:00` : ""}</span>)}</div>{days.map((day) => <div className="ops-heatmap-row" key={day}><span className="ops-heatmap-day">{day}</span>{hours.map((hour) => {
    const value = totals.filter((item) => item.day === day && item.hour === hour).length;
    const opacity = 0.07 + (value / peak) * 0.82;
    return <span key={hour} className="ops-heat-cell" title={`${day} ${hour}:00 · ${value} calls`} style={{ backgroundColor: `rgb(8 126 131 / ${opacity})` }} />;
  })}</div>)}<div className="ops-heatmap-legend"><span>Fewer calls</span><i /><i /><i /><i /><span>More calls</span></div></div>;
}

export function RankingBars({ data, color = "#087e83" }: { data: Array<{ name: string; value: number }>; color?: string }) {
  return <ResponsiveContainer width="100%" height={Math.max(175, data.length * 36)}><BarChart data={data} layout="vertical" margin={{ top: 4, right: 22, left: 12, bottom: 0 }}><CartesianGrid stroke={GRID} horizontal={false} /><XAxis type="number" tick={{ fill: TEXT, fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis type="category" dataKey="name" width={130} tick={{ fill: TEXT, fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip contentStyle={{ border: "1px solid #dfe5eb", borderRadius: 8, fontSize: 12 }} /><Bar dataKey="value" name="Calls" fill={color} radius={[0, 4, 4, 0]} barSize={13} /></BarChart></ResponsiveContainer>;
}

export function LanguageBars({ calls }: { calls: CallRecord[] }) {
  const data = [...new Set(calls.map((call) => call.language))].map((language) => {
    const subset = calls.filter((call) => call.language === language);
    return { name: language, value: subset.length ? Math.round(subset.filter((call) => call.disposition === "CLOSED").length / subset.length * 100) : 0 };
  }).sort((a, b) => b.value - a.value);
  return <ResponsiveContainer width="100%" height={220}><BarChart data={data} margin={{ top: 8, right: 12, left: -18, bottom: 0 }}><CartesianGrid stroke={GRID} vertical={false} /><XAxis dataKey="name" tick={{ fill: TEXT, fontSize: 10 }} axisLine={false} tickLine={false} /><YAxis tickFormatter={(v: number) => `${v}%`} domain={[0, 100]} tick={{ fill: TEXT, fontSize: 10 }} axisLine={false} tickLine={false} /><Tooltip formatter={(value) => [`${Number(value ?? 0)}%`, "Close rate"]} contentStyle={{ border: "1px solid #dfe5eb", borderRadius: 8, fontSize: 12 }} /><Bar dataKey="value" name="Close rate" fill="#5a7baa" radius={[4, 4, 0, 0]} barSize={25} /></BarChart></ResponsiveContainer>;
}

