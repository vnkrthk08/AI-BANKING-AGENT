import { useMemo, useState } from "react";
import { ArrowRight, Pause, Play, Plus } from "@phosphor-icons/react";
import { PageHeading } from "../components/PageHeading";
import { PageState } from "../components/PageState";
import { StatusPill } from "../components/StatusPill";
import { Panel } from "../components/Panel";
import { useDashboard } from "../hooks/DashboardContext";
import { useRole } from "../hooks/useRole";
import { hasAction } from "../config/permissions";
import { dashboardApi } from "../services/dashboardApi";
import type { Campaign } from "../types";

export function CampaignsPage() {
  const { snapshot, loading, error, refresh } = useDashboard();
  const [role] = useRole();
  const [selected, setSelected] = useState<string | null>(null);
  const [notice, setNotice] = useState("");
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState("");
  const canManage = hasAction(role, "manage-campaigns");

  const stats = useMemo(
    () =>
      snapshot?.campaigns.map((item) => ({
        ...item,
        closed: snapshot.calls.filter((call) => call.campaignId === item.id && call.disposition === "CLOSED").length,
        connected: snapshot.calls.filter((call) => call.campaignId === item.id && call.connected).length,
      })) ?? [],
    [snapshot]
  );

  if (!snapshot) return <PageState loading={loading} error={error} onRetry={() => void refresh()} />;
  const activeId = selected ?? snapshot.campaigns[0]?.id;
  const campaign = snapshot.campaigns.find((item) => item.id === activeId);

  async function toggle(id: string, status: string) {
    await dashboardApi.updateCampaign(id, { status });
    await dashboardApi.recordAudit("CAMPAIGN_STATUS_CHANGED", "CAMPAIGN", id, role, `Status updated to ${status}`);
    await refresh();
    setNotice(`Campaign ${status.toLowerCase()} successfully.`);
  }

  async function createCampaign() {
    const title = name.trim();
    if (!title) return;
    const newCamp: Campaign = {
      id: `CMP-${crypto.randomUUID().slice(0, 8).toUpperCase()}`,
      name: title,
      objective: "Service Support & Adoption",
      status: "DRAFT",
      scriptVersion: "v1.1",
      segmentSize: 1250,
      maxAttempts: 2,
      retryGapHours: 24,
      languages: ["English", "Tamil", "Hindi"],
      region: "All India",
      callsDialed: 0,
      answerRate: 0,
      updatedAt: new Date().toISOString(),
    };
    await dashboardApi.createCampaign(newCamp);
    await dashboardApi.recordAudit("CAMPAIGN_CREATED", "CAMPAIGN", newCamp.id, role, `Draft campaign ${newCamp.name} created`);
    await refresh();
    setSelected(newCamp.id);
    setName("");
    setCreating(false);
    setNotice("Draft campaign created successfully.");
  }

  return (
    <>
      <PageHeading
        eyebrow="OUTBOUND PROGRAMS"
        title="Campaigns"
        description="Manage outbound campaigns, retry cadence, conversational scripts, and cohort performance."
        actions={
          canManage && (
            <button className="ops-button ops-button-primary" onClick={() => setCreating((value) => !value)}>
              <Plus size={15} />
              New campaign
            </button>
          )
        }
      />
      {notice && (
        <div className="ops-notice-banner" role="status">
          {notice}
          <button onClick={() => setNotice("")}>Dismiss</button>
        </div>
      )}
      {creating && (
        <form
          className="ops-inline-create"
          onSubmit={(event) => {
            event.preventDefault();
            void createCampaign();
          }}
        >
          <label>
            Campaign name
            <input
              value={name}
              onChange={(event) => setName(event.target.value)}
              placeholder="e.g. Town Bank Mobile App v2.4 Rollout"
              required
            />
          </label>
          <span>Standard retry policy: 2 maximum attempts with a 24-hour spacing window.</span>
          <button className="ops-button ops-button-primary">Create draft</button>
          <button type="button" className="ops-text-button" onClick={() => setCreating(false)}>
            Cancel
          </button>
        </form>
      )}
      <div className="ops-campaign-layout">
        <section className="ops-campaign-list">
          {snapshot.campaigns.map((item) => (
            <button
              key={item.id}
              className={`ops-campaign-row ${activeId === item.id ? "active" : ""}`}
              onClick={() => setSelected(item.id)}
            >
              <span>
                <strong>{item.name}</strong>
                <small>
                  {item.objective} · {item.id}
                </small>
              </span>
              <StatusPill value={item.status} />
              <span className="ops-campaign-mini">
                {item.callsDialed.toLocaleString("en-IN")} dialed <b>{(item.answerRate * 100).toFixed(0)}% answer</b>
              </span>
            </button>
          ))}
        </section>
        {campaign && (
          <div className="ops-campaign-detail">
            <Panel title={campaign.name} subtitle={`${campaign.id} · ${campaign.objective}`} actions={<StatusPill value={campaign.status} />}>
              <div className="ops-campaign-kpis">
                <div>
                  <small>SEGMENT</small>
                  <strong>{campaign.segmentSize.toLocaleString("en-IN")}</strong>
                </div>
                <div>
                  <small>DIALED</small>
                  <strong>{campaign.callsDialed.toLocaleString("en-IN")}</strong>
                </div>
                <div>
                  <small>ANSWER RATE</small>
                  <strong>{(campaign.answerRate * 100).toFixed(1)}%</strong>
                </div>
              </div>
              <div className="ops-fact-list">
                <span>Script version<strong>{campaign.scriptVersion} (Subbu v1.1 Active)</strong></span>
                <span>Retry rules<strong>Up to {campaign.maxAttempts} attempts · {campaign.retryGapHours}h minimum gap</strong></span>
                <span>Languages<strong>{campaign.languages.join(", ")}</strong></span>
                <span>Region<strong>{campaign.region}</strong></span>
                <span>Last updated<strong>{new Date(campaign.updatedAt).toLocaleString("en-IN", { timeZone: "Asia/Kolkata" })} IST</strong></span>
              </div>
              {canManage && (
                <div className="ops-campaign-actions">
                  <button className="ops-button ops-button-secondary" onClick={() => setNotice("Script version Subbu v1.1 locked by compliance policy.")}>
                    Review script version <ArrowRight size={14} />
                  </button>
                  <button
                    className="ops-button ops-button-secondary"
                    onClick={() => void toggle(campaign.id, campaign.status === "ACTIVE" ? "PAUSED" : "ACTIVE")}
                  >
                    {campaign.status === "ACTIVE" ? <><Pause size={14} />Pause campaign</> : <><Play size={14} />Resume campaign</>}
                  </button>
                </div>
              )}
            </Panel>
            <Panel title="Cohort Comparison" subtitle="Comparative response metrics across campaign segments">
              <div className="ops-ab-compare">
                {stats.slice(0, 2).map((item) => (
                  <div key={item.id}>
                    <strong>{item.name}</strong>
                    <span>{item.connected.toLocaleString("en-IN")} connected</span>
                    <div className="ops-meter">
                      <i style={{ width: `${item.answerRate * 100}%` }} />
                    </div>
                    <b>{(item.answerRate * 100).toFixed(1)}% answer rate</b>
                  </div>
                ))}
              </div>
              <p className="ops-helper">Performance metrics refreshed every 5 minutes from telephony gateway logs.</p>
            </Panel>
          </div>
        )}
      </div>
    </>
  );
}
