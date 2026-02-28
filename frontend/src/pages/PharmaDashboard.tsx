import { useState, useEffect } from "react";
import { Building2, TrendingUp, Shield, AlertCircle } from "lucide-react";
import { api } from "../lib/api";
import { BarChart, Bar, XAxis, YAxis, Tooltip, ResponsiveContainer, Cell } from "recharts";

interface Profile {
  slug: string;
  company: string;
  aging_relevance: string;
  aging_signal_strength: number;
}

interface DDResult {
  pharma: string;
  executive_summary: string;
  landscape_stats: Record<string, unknown>;
  top_targets: {
    rank: number;
    company: string;
    stage: string;
    strategy: string;
    strategy_detail: string;
    relevance_score: number;
    matched_interventions: string[];
    risks: string[];
    competitive_advantages: string[];
    acquisition_estimate: { low_usd?: number; high_usd?: number };
  }[];
  category_landscape: Record<string, { count: number; companies: string[] }>;
  hallmark_heatmap: Record<string, { count: number; companies: string[] }>;
}

const STRATEGY_COLORS: Record<string, string> = {
  competitive: "bg-error text-on-error",
  opportunistic: "bg-tertiary text-on-tertiary",
  evaluate: "bg-primary text-on-primary",
  monitor: "bg-outline text-white",
};

function formatUsd(n: number | undefined): string {
  if (!n) return "N/A";
  if (n >= 1e9) return `$${(n / 1e9).toFixed(1)}B`;
  if (n >= 1e6) return `$${(n / 1e6).toFixed(0)}M`;
  return `$${n.toLocaleString()}`;
}

export default function PharmaDashboard() {
  const [profiles, setProfiles] = useState<Profile[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [dd, setDd] = useState<DDResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    api.listPharma().then((data) => {
      const p = (data.profiles || []) as Profile[];
      setProfiles(p);
      if (p.length > 0) setSelected(p[0].slug);
    }).catch(() => setError("Failed to load pharma profiles. Is the API running?"));
  }, []);

  useEffect(() => {
    if (!selected) return;
    setLoading(true);
    setError("");
    api
      .runPharmaDd(selected)
      .then((data) => setDd(data as DDResult))
      .catch((e) => setError(e.message))
      .finally(() => setLoading(false));
  }, [selected]);

  const hallmarkData = dd
    ? Object.entries(dd.hallmark_heatmap)
        .map(([name, { count }]) => ({ name: name.replace(/_/g, " "), count }))
        .sort((a, b) => b.count - a.count)
    : [];

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div className="flex items-center justify-between">
        <div>
          <h2 className="text-2xl font-bold font-heading text-on-surface">Pharma Due Diligence</h2>
          <p className="text-sm text-on-surface-variant mt-1">
            Acquisition landscape analysis for longevity biotech targets
          </p>
        </div>
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
        <div className="flex items-center gap-2 px-4 py-3 bg-error-container border border-error rounded-lg text-sm text-on-error-container">
          <AlertCircle size={16} />
          {error}
        </div>
      )}

      {loading && (
        <div className="flex items-center justify-center py-20">
          <div className="animate-spin w-8 h-8 border-2 border-primary border-t-transparent rounded-full" />
        </div>
      )}

      {dd && !loading && (
        <>
          {/* Executive Summary */}
          {dd.executive_summary && (
            <div className="bg-surface-container-lowest rounded-xl border border-outline-variant p-6">
              <h3 className="text-sm font-semibold text-on-surface-variant uppercase tracking-wider mb-3 font-heading">
                Executive Summary
              </h3>
              <p className="text-sm text-on-surface whitespace-pre-wrap leading-relaxed">
                {dd.executive_summary}
              </p>
            </div>
          )}

          {/* Stats cards */}
          <div className="grid grid-cols-4 gap-4">
            {[
              {
                icon: Building2,
                label: "Biotechs Analysed",
                value: (dd.landscape_stats.total_biotechs_analysed as number) || 0,
              },
              {
                icon: TrendingUp,
                label: "Matched Interventions",
                value: (dd.landscape_stats.total_matched_interventions as number) || 0,
              },
              {
                icon: Shield,
                label: "Tools Available",
                value: ((dd.landscape_stats.tools_available as string[]) || []).length,
              },
              {
                icon: Building2,
                label: "Categories Covered",
                value: (dd.landscape_stats.categories_covered as number) || 0,
              },
            ].map(({ icon: Icon, label, value }) => (
              <div key={label} className="bg-surface-container-lowest rounded-xl border border-outline-variant p-4">
                <div className="flex items-center gap-2 text-on-surface-variant mb-1">
                  <Icon size={14} />
                  <span className="text-xs">{label}</span>
                </div>
                <span className="text-2xl font-bold text-primary">{value}</span>
              </div>
            ))}
          </div>

          {/* Biotech targets table */}
          <div className="bg-surface-container-lowest rounded-xl border border-outline-variant overflow-hidden">
            <div className="px-6 py-4 border-b border-outline-variant">
              <h3 className="font-semibold font-heading text-on-surface">Top Acquisition Targets</h3>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full">
                <thead>
                  <tr className="bg-surface-container text-left text-xs font-medium text-on-surface-variant uppercase">
                    <th className="px-6 py-3">#</th>
                    <th className="px-6 py-3">Company</th>
                    <th className="px-6 py-3">Stage</th>
                    <th className="px-6 py-3">Strategy</th>
                    <th className="px-6 py-3">Relevance</th>
                    <th className="px-6 py-3">Interventions</th>
                    <th className="px-6 py-3">Est. Value</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-outline-variant">
                  {dd.top_targets.map((t) => (
                    <tr key={t.rank} className="hover:bg-surface-container-low">
                      <td className="px-6 py-4 text-sm text-on-surface-variant">{t.rank}</td>
                      <td className="px-6 py-4">
                        <div className="font-medium text-sm text-on-surface">{t.company}</div>
                        {t.strategy_detail && (
                          <div className="text-xs text-on-surface-variant mt-0.5 max-w-xs truncate">
                            {t.strategy_detail}
                          </div>
                        )}
                      </td>
                      <td className="px-6 py-4 text-sm capitalize text-on-surface">{t.stage}</td>
                      <td className="px-6 py-4">
                        <span
                          className={`px-2 py-1 rounded-full text-xs font-medium ${
                            STRATEGY_COLORS[t.strategy] || STRATEGY_COLORS.monitor
                          }`}
                        >
                          {t.strategy}
                        </span>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex items-center gap-2">
                          <div className="w-16 h-2 bg-surface-variant rounded-full overflow-hidden">
                            <div
                              className="h-full bg-primary rounded-full"
                              style={{ width: `${t.relevance_score}%` }}
                            />
                          </div>
                          <span className="text-xs text-on-surface-variant">
                            {t.relevance_score.toFixed(0)}
                          </span>
                        </div>
                      </td>
                      <td className="px-6 py-4">
                        <div className="flex flex-wrap gap-1">
                          {t.matched_interventions.slice(0, 3).map((i) => (
                            <span
                              key={i}
                              className="px-1.5 py-0.5 bg-primary-container text-on-primary-container rounded text-xs"
                            >
                              {i}
                            </span>
                          ))}
                          {t.matched_interventions.length > 3 && (
                            <span className="text-xs text-on-surface-variant">
                              +{t.matched_interventions.length - 3}
                            </span>
                          )}
                        </div>
                      </td>
                      <td className="px-6 py-4 text-sm text-on-surface">
                        {formatUsd(t.acquisition_estimate?.low_usd)} –{" "}
                        {formatUsd(t.acquisition_estimate?.high_usd)}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>

          {/* Hallmark heatmap */}
          {hallmarkData.length > 0 && (
            <div className="bg-surface-container-lowest rounded-xl border border-outline-variant p-6">
              <h3 className="font-semibold font-heading mb-4 text-on-surface">Hallmark Coverage</h3>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={hallmarkData} layout="vertical">
                  <XAxis type="number" />
                  <YAxis
                    type="category"
                    dataKey="name"
                    width={200}
                    tick={{ fontSize: 12 }}
                  />
                  <Tooltip />
                  <Bar dataKey="count" radius={[0, 4, 4, 0]}>
                    {hallmarkData.map((_, i) => (
                      <Cell
                        key={i}
                        fill={i % 2 === 0 ? "rgb(109 94 15)" : "rgb(67 102 78)"}
                      />
                    ))}
                  </Bar>
                </BarChart>
              </ResponsiveContainer>
            </div>
          )}
        </>
      )}

      {!dd && !loading && !error && profiles.length === 0 && (
        <div className="text-center py-20 text-on-surface-variant">
          <Building2 size={48} className="mx-auto mb-4 text-outline" />
          <p className="text-lg font-medium font-heading">No pharma profiles found</p>
          <p className="text-sm mt-1">
            Run <code className="bg-surface-container px-2 py-0.5 rounded">scripts/compile_profiles.py</code> to generate profiles.
          </p>
        </div>
      )}
    </div>
  );
}
