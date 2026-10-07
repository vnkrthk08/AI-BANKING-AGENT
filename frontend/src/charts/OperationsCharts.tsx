import { Bar, BarChart, CartesianGrid, Cell, Line, LineChart, Pie, PieChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import type { CallRecord } from "../types";
import { formatDate } from "../services/selectors";

const OUTCOME_COLORS: Record<string, string> = { CLOSED: "#27805f", CALLBACK_SCHEDULED: "#d29132", ESCALATED: "#b74747", NOT_INTERESTED: "#8793a4", BUSY: "#d3b461", NO_ANSWER: "#aab3c0", DND: "#556276", FAILED: "#c6cbd3" };

export function DrillChart({ children, onDrill, label = "Open filtered call log" }: { children: React.ReactNode; onDrill: () => void; label?: string }) {
  return <div className="ops-chart-drill" role="link" tabIndex={0} aria-label={label} onClick={onDrill} onKeyDown={(event) => { if (event.key === "Enter" || event.key === " ") { event.preventDefault(); onDrill(); } }}>{children}</div>;
}

export function OutcomeDonut({ calls }: { calls: CallRecord[] }) {
  const values = new Map<string, number>();
  calls.forEach((call) => { if (call.disposition) values.set(call.disposition, (values.get(call.disposition) ?? 0) + 1); });
  const data = [...values].map(([name, value]) => ({ name: name.replaceAll("_", " "), value, key: name }));
  return (
    <ResponsiveContainer width="100%" height={230}>
      <PieChart>
        <Pie data={data} dataKey="value" nameKey="name" innerRadius={64} outerRadius={92} paddingAngle={2} stroke="none">
          {data.map((item) => <Cell key={item.key} fill={OUTCOME_COLORS[item.key] ?? "#7f8b9e"} />)}
        </Pie>
        <Tooltip formatter={(value) => [Number(value ?? 0).toLocaleString("en-IN"), "Calls"]} contentStyle={{ border: "1px solid #e2e8f0", borderRadius: 8, fontSize: 13, background: "#ffffff", boxShadow: "0 4px 6px -1px rgba(0,0,0,0.06)", color: "#0f172a" }} />
        <text x="50%" y="47%" textAnchor="middle" fill="#0f172a" fontSize="24" fontWeight="800">{calls.length.toLocaleString("en-IN")}</text>
        <text x="50%" y="58%" textAnchor="middle" fill="#64748b" fontSize="12" fontWeight="500">calls in view</text>
      </PieChart>
    </ResponsiveContainer>
  );
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
  return <ResponsiveContainer width="100%" height={250}><LineChart data={data} margin={{ top: 12, right: 14, left: -16, bottom: 0 }}><CartesianGrid stroke="#f1f5f9" vertical={false} /><XAxis dataKey="day" tick={{ fill: "#64748b", fontSize: 11 }} axisLine={false} tickLine={false} /><YAxis tick={{ fill: "#64748b", fontSize: 11 }} axisLine={false} tickLine={false} /><Tooltip contentStyle={{ border: "1px solid #e2e8f0", borderRadius: 8, fontSize: 13, background: "#ffffff", boxShadow: "0 4px 6px -1px rgba(0,0,0,0.06)", color: "#0f172a" }} /><Line type="monotone" dataKey="calls" name="Calls dialed" stroke="#0d9488" strokeWidth={2.5} dot={false} activeDot={{ r: 5 }} /><Line type="monotone" dataKey="closed" name="Closed" stroke="#475569" strokeWidth={2} dot={false} activeDot={{ r: 4 }} /></LineChart></ResponsiveContainer>;
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
  return <div className="ops-heatmap"><div className="ops-heatmap-hours"><span className="ops-heatmap-day-spacer" />{hours.map((hour) => <span key={hour} style={{ textAlign: "center" }}>{hour % 3 === 0 ? `${hour}:00` : ""}</span>)}</div>{days.map((day) => <div className="ops-heatmap-row" key={day}><span className="ops-heatmap-day">{day}</span>{hours.map((hour) => {
    const value = totals.filter((item) => item.day === day && item.hour === hour).length;
    const opacity = 0.07 + (value / peak) * 0.82;
    return <span key={hour} className="ops-heat-cell" title={`${day} ${hour}:00 · ${value} calls`} style={{ backgroundColor: `rgb(8 126 131 / ${opacity})` }} />;
  })}</div>)}<div className="ops-heatmap-legend"><span>Fewer calls</span><i /><i /><i /><i /><span>More calls</span></div></div>;
}

export function RankingBars({ data, color = "#0d9488" }: { data: Array<{ name: string; value: number }>; color?: string }) {
  return (
    <ResponsiveContainer width="100%" height={Math.max(180, data.length * 38)}>
      <BarChart data={data} layout="vertical" margin={{ top: 6, right: 24, left: 14, bottom: 0 }}>
        <CartesianGrid stroke="#f1f5f9" horizontal={false} />
        <XAxis type="number" tick={{ fill: "#64748b", fontSize: 11 }} axisLine={false} tickLine={false} />
        <YAxis type="category" dataKey="name" width={140} tick={{ fill: "#475569", fontSize: 12, fontWeight: 500 }} axisLine={false} tickLine={false} />
        <Tooltip contentStyle={{ border: "1px solid #e2e8f0", borderRadius: 8, fontSize: 12, background: "#ffffff", boxShadow: "0 4px 6px -1px rgba(0,0,0,0.06)", color: "#0f172a" }} />
        <Bar dataKey="value" name="Calls" fill={color} radius={[0, 6, 6, 0]} barSize={16} />
      </BarChart>
    </ResponsiveContainer>
  );
}

export function LanguageBars({ calls }: { calls: CallRecord[] }) {
  const data = [...new Set(calls.map((call) => call.language))].map((language) => {
    const subset = calls.filter((call) => call.language === language);
    return { name: language, value: subset.length ? Math.round(subset.filter((call) => call.disposition === "CLOSED").length / subset.length * 100) : 0 };
  }).sort((a, b) => b.value - a.value);
  return (
    <ResponsiveContainer width="100%" height={230}>
      <BarChart data={data} margin={{ top: 10, right: 14, left: -14, bottom: 0 }}>
        <CartesianGrid stroke="#f1f5f9" vertical={false} />
        <XAxis dataKey="name" tick={{ fill: "#64748b", fontSize: 12, fontWeight: 500 }} axisLine={false} tickLine={false} />
        <YAxis tickFormatter={(v: number) => `${v}%`} domain={[0, 100]} tick={{ fill: "#64748b", fontSize: 11 }} axisLine={false} tickLine={false} />
        <Tooltip formatter={(value) => [`${Number(value ?? 0)}%`, "Close rate"]} contentStyle={{ border: "1px solid #e2e8f0", borderRadius: 8, fontSize: 12, background: "#ffffff", boxShadow: "0 4px 6px -1px rgba(0,0,0,0.06)", color: "#0f172a" }} />
        <Bar dataKey="value" name="Close rate" fill="#0d9488" radius={[6, 6, 0, 0]} barSize={28} />
      </BarChart>
    </ResponsiveContainer>
  );
}

