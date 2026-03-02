import { useState, useEffect } from "react";
import { Microscope, ExternalLink, AlertTriangle, Shield, Users } from "lucide-react";
import { api } from "../lib/api";

interface BiotechProfile {
  company: string;
  ticker: string | null;
  founded: number | null;
  hq: string | null;
  stage: string;
  total_funding_usd: number | null;
  pipeline: {
    compound: string;
    target: string;
    mechanism: string;
    phase: string;
    hallmarks: string[];
    source: string;
  }[];
  hallmarks_targeted: string[];
  key_people: { name: string; role: string; background: string }[];
  investors_notable: string[];
  risks: string[];
  competitive_advantages: string[];
  acquisition_estimate: { low_usd?: number; high_usd?: number; methodology?: string } | null;
  sources: string[];
}

interface ProfileListItem {
  slug: string;
  company: string;
  stage: string;
}

function formatUsd(n: number | undefined): string {
  if (!n) return "N/A";
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  return `$${n.toLocaleString()}`;
}

export default function BiotechDeepDive() {
  const [profiles, setProfiles] = useState<ProfileListItem[]>([]);
  const [selected, setSelected] = useState("");
  const [profile, setProfile] = useState<BiotechProfile | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.listBiotech().then((data) => {
      const p = (data.profiles || []) as ProfileListItem[];
      setProfiles(p);
      if (p.length > 0) setSelected(p[0].slug);
    }).catch(() => setError("Failed to load biotech profiles."));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setLoading(true);
    setError("");
    api
      .getBiotech(selected)
      .then((data) => setProfile(data as BiotechProfile))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [selected]);

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between">
        <h2 className="text-2xl font-bold font-heading text-on-surface">Biotech Deep Dive</h2>
        <select
          value={selected}
          onChange={(e) => setSelected(e.target.value)}
          className="px-4 py-2 border border-outline-variant rounded-lg text-sm bg-surface-container-lowest text-on-surface"
        >
          {profiles.map((p) => (
            <option key={p.slug} value={p.slug}>
              {p.company}
            </option>
          ))}
        </select>
      </div>

      {error && (
        <div className="px-4 py-3 bg-error-container border border-error rounded-lg text-sm text-on-error-container">
          {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-20">
          <div className="animate-spin w-8 h-8 border-2 border-primary border-t-transparent rounded-full" />
        </div>
      )}

      {profile && !loading && (
        <>
          {/* Header card */}
          <div className="bg-surface-container-lowest rounded-xl border border-outline-variant p-6">
            <div className="flex items-start justify-between">
              <div>
                <h3 className="text-xl font-bold font-heading text-on-surface">{profile.company}</h3>
                <div className="flex gap-4 mt-2 text-sm text-on-surface-variant">
                  {profile.ticker && <span>Ticker: {profile.ticker}</span>}
                  {profile.founded && <span>Founded: {profile.founded}</span>}
                  {profile.hq && <span>{profile.hq}</span>}
                </div>
              </div>
              <div className="text-right">
                <span className="px-3 py-1 bg-primary-container text-on-primary-container rounded-full text-sm font-medium capitalize">
                  {profile.stage}
                </span>
                {profile.total_funding_usd && (
                  <div className="mt-2 text-sm text-on-surface-variant">
                    Funding: {formatUsd(profile.total_funding_usd)}
                  </div>
                )}
              </div>
            </div>

            {/* Hallmarks */}
            {profile.hallmarks_targeted.length > 0 && (
              <div className="mt-4 flex flex-wrap gap-1.5">
                {profile.hallmarks_targeted.map((h) => (
                  <span
                    key={h}
                    className="px-2 py-0.5 bg-tertiary-container text-on-tertiary-container rounded text-xs"
                  >
                    {h.replace(/_/g, " ")}
                  </span>
                ))}
              </div>
            )}
          </div>

          {/* Pipeline */}
          {profile.pipeline.length > 0 && (
            <div className="bg-surface-container-lowest rounded-xl border border-outline-variant overflow-hidden">
              <div className="px-6 py-4 border-b border-outline-variant">
                <h3 className="font-semibold font-heading text-on-surface">Pipeline</h3>
              </div>
              <table className="w-full">
                <thead>
                  <tr className="bg-surface-container text-left text-xs font-medium text-on-surface-variant uppercase">
                    <th className="px-6 py-3">Compound</th>
                    <th className="px-6 py-3">Target</th>
                    <th className="px-6 py-3">Mechanism</th>
                    <th className="px-6 py-3">Phase</th>
                    <th className="px-6 py-3">Hallmarks</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-outline-variant">
                  {profile.pipeline.map((c, i) => (
                    <tr key={i} className="hover:bg-surface-container-low">
                      <td className="px-6 py-3 text-sm font-medium text-on-surface">{c.compound}</td>
                      <td className="px-6 py-3 text-sm text-on-surface-variant">{c.target}</td>
                      <td className="px-6 py-3 text-sm text-on-surface-variant">{c.mechanism}</td>
                      <td className="px-6 py-3 text-sm capitalize text-on-surface">{c.phase}</td>
                      <td className="px-6 py-3">
                        <div className="flex flex-wrap gap-1">
                          {c.hallmarks.slice(0, 2).map((h) => (
                            <span
                              key={h}
                              className="px-1.5 py-0.5 bg-tertiary-container text-on-tertiary-container rounded text-xs"
                            >
                              {h.replace(/_/g, " ")}
                            </span>
                          ))}
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}

          {/* Two-column: Risks + Advantages */}
          <div className="grid grid-cols-2 gap-4">
            <div className="bg-surface-container-lowest rounded-xl border border-outline-variant p-6">
              <h3 className="font-semibold font-heading flex items-center gap-2 mb-3 text-on-surface">
                <AlertTriangle size={16} className="text-error" />
                Risks
              </h3>
              <ul className="space-y-2">
                {profile.risks.map((r, i) => (
                  <li key={i} className="text-sm text-on-surface-variant flex gap-2">
                    <span className="text-error mt-1">&#x2022;</span>
                    {r}
                  </li>
                ))}
              </ul>
            </div>

            <div className="bg-surface-container-lowest rounded-xl border border-outline-variant p-6">
              <h3 className="font-semibold font-heading flex items-center gap-2 mb-3 text-on-surface">
                <Shield size={16} className="text-tertiary" />
                Competitive Advantages
              </h3>
              <ul className="space-y-2">
                {profile.competitive_advantages.map((a, i) => (
                  <li key={i} className="text-sm text-on-surface-variant flex gap-2">
                    <span className="text-tertiary mt-1">&#x2022;</span>
                    {a}
                  </li>
                ))}
              </ul>
            </div>
          </div>

          {/* Key People + Investors */}
          <div className="grid grid-cols-2 gap-4">
            {profile.key_people.length > 0 && (
              <div className="bg-surface-container-lowest rounded-xl border border-outline-variant p-6">
                <h3 className="font-semibold font-heading flex items-center gap-2 mb-3 text-on-surface">
                  <Users size={16} className="text-primary" />
                  Key People
                </h3>
                <div className="space-y-3">
                  {profile.key_people.map((p, i) => (
                    <div key={i}>
                      <div className="text-sm font-medium text-on-surface">{p.name}</div>
                      <div className="text-xs text-on-surface-variant">{p.role}</div>
                    </div>
                  ))}
                </div>
              </div>
            )}

            {profile.investors_notable.length > 0 && (
              <div className="bg-surface-container-lowest rounded-xl border border-outline-variant p-6">
                <h3 className="font-semibold font-heading mb-3 text-on-surface">Notable Investors</h3>
                <div className="flex flex-wrap gap-2">
                  {profile.investors_notable.map((inv, i) => (
                    <span
                      key={i}
                      className="px-2 py-1 bg-secondary-container text-on-secondary-container rounded text-xs"
                    >
                      {inv}
                    </span>
                  ))}
                </div>
              </div>
            )}
          </div>

          {/* Acquisition estimate */}
          {profile.acquisition_estimate && (
            <div className="bg-surface-container-lowest rounded-xl border border-outline-variant p-6">
              <h3 className="font-semibold font-heading mb-3 text-on-surface">Acquisition Estimate</h3>
              <div className="text-2xl font-bold text-primary">
                {formatUsd(profile.acquisition_estimate.low_usd)} –{" "}
                {formatUsd(profile.acquisition_estimate.high_usd)}
              </div>
              {profile.acquisition_estimate.methodology && (
                <p className="text-sm text-on-surface-variant mt-2">
                  {profile.acquisition_estimate.methodology}
                </p>
              )}
            </div>
          )}

          {/* Sources */}
          {profile.sources.length > 0 && (
            <div className="bg-surface-container-lowest rounded-xl border border-outline-variant p-6">
              <h3 className="font-semibold font-heading mb-3 text-on-surface">Sources</h3>
              <ul className="space-y-1">
                {profile.sources.map((s, i) => (
                  <li key={i} className="text-sm text-primary flex items-center gap-1">
                    <ExternalLink size={12} />
                    <a href={s} target="_blank" rel="noreferrer" className="hover:underline truncate">
                      {s}
                    </a>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}

      {!profile && !loading && !error && profiles.length === 0 && (
        <div className="text-center py-20 text-on-surface-variant">
          <Microscope size={48} className="mx-auto mb-4 text-outline" />
          <p className="text-lg font-medium font-heading">No biotech profiles found</p>
          <p className="text-sm mt-1">
            Run <code className="bg-surface-container px-2 py-0.5 rounded">scripts/compile_profiles.py --type biotech</code>
          </p>
        </div>
      )}
    </div>
  );
}
