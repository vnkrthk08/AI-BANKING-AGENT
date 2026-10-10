import { useEffect, useMemo, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { DownloadSimple, Phone, Plus, UploadSimple, UserList } from "@phosphor-icons/react";
import { useApi } from "../hooks/useApi";
import { useAuth } from "../auth/AuthContext";
import { apiFetch, apiJson } from "../services/http";
import {
  Badge,
  CallTimeline,
  Drawer,
  outcomeLabel,
  Empty,
  ErrorNote,
  Loading,
  Modal,
  PageHead,
  Panel,
  Tabs,
  fmtDateTime,
  fmtDuration,
  titleCase,
  useToast,
} from "../components/ui";

interface Call {
  id: string;
  sessionId: string;
  customerRef: string;
  maskedPhone: string;
  campaignName: string;
  language: string;
  startedAt: string;
  durationSec: number;
  disposition: string | null;
  status: string;
  channel: string;
  resolutionMode: string;
  escalationId: string | null;
  callbackId: string | null;
  recordingAvailable: boolean;
  kuralState: string;
  consented: boolean;
}
interface Turn {
  id: string;
  speaker: string;
  text: string;
  time: string;
  redacted: boolean;
}
interface Customer {
  customer_ref: string;
  full_name: string;
  phone: string;
  preferred_language: string;
  app_status: string;
  dnd_status: boolean;
  branch: string;
  account_type: string;
}

async function download(path: string, filename: string) {
  const r = await apiFetch(path);
  if (!r.ok) throw new Error(`Export failed (${r.status})`);
  const url = URL.createObjectURL(await r.blob());
  const a = Object.assign(document.createElement("a"), { href: url, download: filename });
  a.click();
  URL.revokeObjectURL(url);
}

function CallDrawer({ call, onClose }: { call: Call; onClose: () => void }) {
  const { can } = useAuth();
  const transcript = useApi<Turn[]>(can("transcript:read") ? `/api/calls/${call.id}/transcript` : null);
  const [audio, setAudio] = useState<string | null>(null);
  const [audioErr, setAudioErr] = useState<string | null>(null);

  useEffect(() => () => { if (audio) URL.revokeObjectURL(audio); }, [audio]);

  const loadAudio = async () => {
    const r = await apiFetch(`/api/calls/${call.id}/recording`);
    if (!r.ok) {
      setAudioErr(r.status === 404 ? "No recording is stored for this call." : "Recording access was denied.");
      return;
    }
    setAudio(URL.createObjectURL(await r.blob()));
  };

  const timelineSteps = [
    {
      label: "Call initiated",
      time: fmtDateTime(call.startedAt),
      detail: `Channel: ${titleCase(call.channel)} · Language: ${call.language}`,
      status: "done" as const,
    },
    {
      label: "Customer connection",
      detail: call.consented ? "Consent captured & recorded" : "Consent pending / in-progress",
      status: call.consented ? ("done" as const) : ("active" as const),
    },
    {
      label: "Voice AI processing",
      detail: `State: ${titleCase(call.kuralState)} · Duration: ${fmtDuration(call.durationSec)}`,
      status: "done" as const,
    },
    {
      label: `Disposition: ${outcomeLabel(call.disposition ?? call.status)}`,
      detail: call.escalationId
        ? `Escalated to human staff (Case: ${call.escalationId})`
        : call.callbackId
        ? `Callback booked (ID: ${call.callbackId})`
        : "Autonomous AI resolution completed",
      status: (call.disposition === "CLOSED" || call.status === "COMPLETED") ? ("done" as const) : ("active" as const),
    },
  ];

  return (
    <Drawer title={call.customerRef} sub={`${call.id} · ${fmtDateTime(call.startedAt)}`} onClose={onClose}>
      <div className="actions">
        <Badge value={call.disposition ?? call.status}>{outcomeLabel(call.disposition ?? call.status)}</Badge>
        <Badge value={call.channel} tone="" />
        <span className="badge plain">{fmtDuration(call.durationSec)}</span>
      </div>

      <dl className="kv">
        <dt>Phone</dt>
        <dd className="num">{call.maskedPhone || "—"}</dd>
        <dt>Language</dt>
        <dd>{call.language}</dd>
        <dt>Source</dt>
        <dd>{call.campaignName}</dd>
        <dt>Final state</dt>
        <dd>{titleCase(call.kuralState)}</dd>
        <dt>Consent captured</dt>
        <dd>{call.consented ? "Yes (captured)" : "Not recorded"}</dd>
        <dt>Linked case / cb</dt>
        <dd>{call.escalationId ?? "—"} / {call.callbackId ?? "—"}</dd>
      </dl>

      {/* Visual Call Lifecycle Timeline */}
      <section>
        <h3 className="section-title">Call Timeline</h3>
        <CallTimeline steps={timelineSteps} />
      </section>

      {can("recording:read") && (
        <section>
          <h3 className="section-title">Audio Recording</h3>
          {audio ? (
            <audio controls src={audio} style={{ width: "100%", borderRadius: 8 }} />
          ) : call.recordingAvailable ? (
            <button className="btn" onClick={loadAudio}>
              Load recording (access is audited)
            </button>
          ) : (
            <p className="muted small" style={{ margin: 0 }}>
              No audio recording stored for this call.
            </p>
          )}
          {audioErr && <p className="small muted">{audioErr}</p>}
        </section>
      )}

      <section>
        <h3 className="section-title">Transcript</h3>
        {!can("transcript:read") ? (
          <p className="muted small">Your role cannot view transcripts.</p>
        ) : transcript.loading ? (
          <Loading rows={3} />
        ) : !transcript.data?.length ? (
          <p className="muted small" style={{ margin: 0 }}>
            No conversation turns were recorded.
          </p>
        ) : (
          <div className="stack" style={{ gap: 10 }}>
            {transcript.data.map((t) => (
              <div key={t.id} className={`msg ${t.speaker === "CUSTOMER" ? "cust" : "ava"}`}>
                <small>
                  {t.speaker === "CUSTOMER" ? "Customer" : "Subbu"}
                  {t.redacted ? " · redacted" : ""}
                </small>
                {t.text}
              </div>
            ))}
          </div>
        )}
      </section>
    </Drawer>
  );
}

function Customers() {
  const { can } = useAuth();
  const toast = useToast();
  const [q, setQ] = useState("");
  const { data, error, loading, reload } = useApi<Customer[]>(
    `/api/customers?limit=200${q ? `&search=${encodeURIComponent(q)}` : ""}`,
    [q]
  );
  const [adding, setAdding] = useState(false);
  const [form, setForm] = useState({ full_name: "", phone: "", preferred_language: "English", branch: "" });
  const [msg, setMsg] = useState<string | null>(null);

  const save = async () => {
    try {
      await apiJson("/api/customers", { method: "POST", body: JSON.stringify(form) });
      toast.ok("Customer added", `${form.full_name} saved to directory.`);
      setAdding(false);
      setForm({ full_name: "", phone: "", preferred_language: "English", branch: "" });
      void reload();
    } catch (e) {
      const em = e instanceof Error ? e.message : "Could not save";
      setMsg(em);
      toast.bad("Could not save customer", em);
    }
  };

  const importCsv = async (file: File) => {
    const fd = new FormData();
    fd.append("file", file);
    try {
      const r = await apiJson<{ imported: number; skipped: number }>("/api/customers/import", {
        method: "POST",
        body: fd,
      });
      toast.ok("Import successful", `Imported ${r.imported} customer(s), skipped ${r.skipped}.`);
      setMsg(`Imported ${r.imported}, skipped ${r.skipped}.`);
      void reload();
    } catch (e) {
      const em = e instanceof Error ? e.message : "Import failed";
      setMsg(em);
      toast.bad("Import failed", em);
    }
  };

  return (
    <Panel
      flush
      title="Customer directory"
      sub="Phone numbers are masked for data privacy"
      actions={
        can("customer:write") && (
          <>
            <label className="btn">
              <UploadSimple size={16} /> Import CSV
              <input
                type="file"
                accept=".csv"
                hidden
                onChange={(e) => e.target.files?.[0] && void importCsv(e.target.files[0])}
              />
            </label>
            <button className="btn primary" onClick={() => setAdding(true)}>
              <Plus size={16} /> Add customer
            </button>
          </>
        )
      }
    >
      <div className="toolbar">
        <input
          className="input"
          placeholder="Search customer name or reference..."
          value={q}
          onChange={(e) => setQ(e.target.value)}
          aria-label="Search customers"
        />
      </div>
      {msg && (
        <div className="alert info" style={{ margin: 12 }}>
          <span className="grow">{msg}</span>
          <button className="btn sm" onClick={() => setMsg(null)}>
            Dismiss
          </button>
        </div>
      )}
      {error ? (
        <div style={{ padding: 12 }}>
          <ErrorNote error={error} onRetry={reload} />
        </div>
      ) : loading ? (
        <Loading />
      ) : !data?.length ? (
        <Empty
          icon={<UserList size={24} />}
          title="No customers found"
          text="Add a customer or import a CSV (columns: full_name, phone, preferred_language)."
        />
      ) : (
        <div className="table-wrap">
          <table className="t">
            <thead>
              <tr>
                <th>Customer</th>
                <th>Masked phone</th>
                <th>Language</th>
                <th>App status</th>
                <th>Contact policy</th>
              </tr>
            </thead>
            <tbody>
              {data.map((c) => (
                <tr key={c.customer_ref}>
                  <td className="primary-cell">
                    <b>{c.full_name}</b>
                    <span>
                      {c.customer_ref} · {c.branch || "Headquarters"}
                    </span>
                  </td>
                  <td className="num">{c.phone}</td>
                  <td>{c.preferred_language}</td>
                  <td>{titleCase(c.app_status)}</td>
                  <td>
                    {c.dnd_status ? <Badge tone="bad">DND (Opted Out)</Badge> : <Badge tone="ok">Callable</Badge>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {adding && (
        <Modal
          title="Add customer"
          onClose={() => setAdding(false)}
          footer={
            <>
              <button className="btn" onClick={() => setAdding(false)}>
                Cancel
              </button>
              <button className="btn primary" disabled={!form.full_name || !form.phone} onClick={save}>
                Save customer
              </button>
            </>
          }
        >
          <label className="field">
            Full name
            <input
              className="input"
              value={form.full_name}
              onChange={(e) => setForm({ ...form, full_name: e.target.value })}
              placeholder="e.g. Ramesh Kumar"
            />
          </label>
          <label className="field">
            Mobile number
            <input
              className="input"
              inputMode="tel"
              placeholder="98765 43210"
              value={form.phone}
              onChange={(e) => setForm({ ...form, phone: e.target.value })}
            />
            <small>Indian mobile number; stored securely and displayed masked.</small>
          </label>
          <label className="field">
            Preferred language
            <select
              className="select"
              value={form.preferred_language}
              onChange={(e) => setForm({ ...form, preferred_language: e.target.value })}
            >
              {["English", "Hindi", "Tamil", "Telugu", "Kannada", "Marathi", "Bengali"].map((l) => (
                <option key={l}>{l}</option>
              ))}
            </select>
          </label>
          <label className="field">
            Branch
            <input
              className="input"
              value={form.branch}
              onChange={(e) => setForm({ ...form, branch: e.target.value })}
              placeholder="e.g. T. Nagar Branch"
            />
          </label>
        </Modal>
      )}
    </Panel>
  );
}

export function CallsHubPage() {
  const { can } = useAuth();
  const toast = useToast();
  const [params, setParams] = useSearchParams();
  const tab = (params.get("tab") as "history" | "live" | "customers") || "history";
  const { data, error, loading, reload } = useApi<Call[]>("/api/calls?limit=500");
  const [q, setQ] = useState("");
  const [disp, setDisp] = useState("ALL");
  const [open, setOpen] = useState<Call | null>(null);
  const [exportErr, setExportErr] = useState<string | null>(null);

  const calls = data ?? [];
  const live = calls.filter((c) => c.status === "IN_PROGRESS" || c.status === "DIALING");
  const dispositions = useMemo(
    () => Array.from(new Set(calls.map((c) => c.disposition).filter(Boolean))) as string[],
    [calls]
  );
  const rows = calls.filter(
    (c) =>
      (disp === "ALL" || c.disposition === disp) &&
      (!q || `${c.id} ${c.customerRef} ${c.maskedPhone}`.toLowerCase().includes(q.toLowerCase()))
  );

  const handleExport = async () => {
    try {
      toast.info("Preparing export", "Generating calls.csv...");
      await download("/api/calls/export", "calls.csv");
      toast.ok("Export complete", "Downloaded calls.csv");
    } catch (e) {
      const msg = e instanceof Error ? e.message : "Export failed";
      setExportErr(msg);
      toast.bad("Export failed", msg);
    }
  };

  return (
    <>
      <PageHead
        title="Calls"
        sub="Every AI and telephony call with verified outcome, live transcript, timeline and audited recordings."
        actions={
          can("report:export") && (
            <button className="btn" onClick={handleExport}>
              <DownloadSimple size={16} /> Export CSV
            </button>
          )
        }
      />

      {exportErr && <ErrorNote error={exportErr} />}

      <Tabs
        value={tab}
        onChange={(t) => setParams({ tab: t })}
        items={[
          { key: "history", label: "History", count: calls.length },
          { key: "live", label: "In progress", count: live.length, pulse: live.length > 0 },
          ...(can("customer:read") ? [{ key: "customers" as const, label: "Customers" }] : []),
        ]}
      />

      {tab === "customers" ? (
        <Customers />
      ) : (
        <Panel flush>
          {tab === "history" && (
            <div className="toolbar">
              <input
                className="input"
                placeholder="Search call ID, customer name or phone..."
                value={q}
                onChange={(e) => setQ(e.target.value)}
                aria-label="Search calls"
              />
              <select
                className="select"
                value={disp}
                onChange={(e) => setDisp(e.target.value)}
                aria-label="Filter by outcome"
              >
                <option value="ALL">All outcomes</option>
                {dispositions.map((d) => (
                  <option key={d} value={d}>
                    {outcomeLabel(d)}
                  </option>
                ))}
              </select>
            </div>
          )}

          {error ? (
            <div style={{ padding: 12 }}>
              <ErrorNote error={error} onRetry={reload} />
            </div>
          ) : loading ? (
            <Loading />
          ) : (tab === "live" ? live : rows).length === 0 ? (
            <Empty
              icon={<Phone size={24} />}
              title={tab === "live" ? "No calls currently in progress" : calls.length ? "No calls match filters" : "No calls recorded yet"}
              text={
                tab === "live"
                  ? "Active Voice Studio sessions and telephony dial-ins appear here with live turn indicators."
                  : "Calls are recorded here as soon as a Voice Studio session or campaign dial starts."
              }
            />
          ) : (
            <div className="table-wrap">
              <table className="t">
                <thead>
                  <tr>
                    <th>Customer</th>
                    <th>Started</th>
                    <th>Channel</th>
                    <th>Duration</th>
                    <th>Outcome</th>
                    <th>Handled by</th>
                  </tr>
                </thead>
                <tbody>
                  {(tab === "live" ? live : rows).map((c) => (
                    <tr
                      key={c.id}
                      className="click"
                      onClick={() => setOpen(c)}
                      tabIndex={0}
                      onKeyDown={(e) => e.key === "Enter" && setOpen(c)}
                    >
                      <td className="primary-cell">
                        <b>{c.customerRef}</b>
                        <span className="num">{c.maskedPhone || c.id}</span>
                      </td>
                      <td className="num">{fmtDateTime(c.startedAt)}</td>
                      <td>{titleCase(c.channel)}</td>
                      <td className="num">{fmtDuration(c.durationSec)}</td>
                      <td>
                        <Badge value={c.disposition ?? c.status}>
                          {outcomeLabel(c.disposition ?? c.status)}
                        </Badge>
                      </td>
                      <td>{c.escalationId ? "Human follow-up" : "AI Autonomous"}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
      )}

      {open && <CallDrawer call={open} onClose={() => setOpen(null)} />}
    </>
  );
}
