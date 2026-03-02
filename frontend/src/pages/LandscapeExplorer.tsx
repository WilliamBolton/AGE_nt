import { useState, useEffect } from "react";
import { Map, Filter } from "lucide-react";
import { api } from "../lib/api";
import {
  ScatterChart,
  Scatter,
  XAxis,
  YAxis,
  Tooltip,
  ResponsiveContainer,
  ZAxis,
} from "recharts";

interface LandscapeEntry {
  name: string;
  document_count: number;
  confidence: number;
  source_types: number;
}

interface ScatterPoint {
  name: string;
  docs: number;
  confidence: number;
  sources: number;
  x: number;
  y: number;
}

export default function LandscapeExplorer() {
  const [entries, setEntries] = useState<LandscapeEntry[]>([]);
  const [scatterData, setScatterData] = useState<ScatterPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [toolCount, setToolCount] = useState(0);
  const [minDocs, setMinDocs] = useState(4);

  useEffect(() => {
    Promise.all([api.landscapeScores(), api.listTools()])
      .then(([landscape, toolData]) => {
        setEntries(landscape.interventions || []);
        setToolCount(toolData.count || 0);
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const filtered = entries.filter((i) => i.document_count >= minDocs);
    const data: ScatterPoint[] = filtered.map((i) => ({
      name: i.name,
      docs: i.document_count,
      confidence: i.confidence,
      sources: i.source_types,
      x: i.document_count,
      y: i.confidence,
    }));
    setScatterData(data);
  }, [entries, minDocs]);

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div>
        <h2 className="text-2xl font-bold font-heading text-on-surface">Landscape Explorer</h2>
        <p className="text-sm text-on-surface-variant mt-1">
          Evidence volume vs confidence across {entries.length} interventions.{" "}
          {toolCount} analysis tools available.
        </p>
      </div>

      {/* Filters */}
      <div className="bg-surface-container-lowest rounded-xl border border-outline-variant p-4 flex items-center gap-6">
        <Filter size={16} className="text-outline" />
        <div className="flex items-center gap-2">
          <label className="text-sm text-on-surface-variant">Min documents:</label>
          <input
            type="range"
            min={0}
            max={100}
            value={minDocs}
            onChange={(e) => setMinDocs(Number(e.target.value))}
            className="w-32 accent-primary"
          />
          <span className="text-sm font-medium w-8 text-on-surface">{minDocs}</span>
        </div>
        <div className="text-sm text-on-surface-variant">
          Showing {scatterData.length} of {entries.length} interventions
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="animate-spin w-8 h-8 border-2 border-primary border-t-transparent rounded-full" />
        </div>
      ) : (
        <>
          {/* Scatter plot: Documents (x) vs Confidence Score (y) */}
          <div className="bg-surface-container-lowest rounded-xl border border-outline-variant p-6">
            <h3 className="font-semibold font-heading mb-1 text-on-surface">
              Evidence Volume vs Confidence
            </h3>
            <p className="text-xs text-on-surface-variant mb-4">
              X = total documents ingested. Y = evidence confidence score (0-100, based on study quality + human data gating).
              Bubble size = source diversity.
            </p>
            {scatterData.length > 0 ? (
              <ResponsiveContainer width="100%" height={420}>
                <ScatterChart margin={{ bottom: 20, left: 10 }}>
                  <XAxis
                    type="number"
                    dataKey="x"
                    name="Documents"
                    label={{ value: "Total Documents", position: "bottom", offset: 0 }}
                  />
                  <YAxis
                    type="number"
                    dataKey="y"
                    name="Confidence"
                    domain={[0, 100]}
                    label={{ value: "Evidence Confidence (0-100)", angle: -90, position: "insideLeft", offset: 10 }}
                  />
                  <ZAxis type="number" dataKey="sources" range={[40, 400]} name="Source Types" />
                  <Tooltip
                    content={({ payload }) => {
                      if (!payload?.length) return null;
                      const d = payload[0].payload as ScatterPoint;
                      return (
                        <div className="bg-surface-container-lowest shadow-lg border border-outline-variant rounded-lg px-3 py-2">
                          <div className="font-medium text-sm text-on-surface capitalize">{d.name}</div>
                          <div className="text-xs text-on-surface-variant space-y-0.5 mt-1">
                            <div>{d.docs} documents</div>
                            <div>Confidence: <span className="font-medium text-primary">{d.confidence.toFixed(1)}</span>/100</div>
                            <div>{d.sources} source types</div>
                          </div>
                        </div>
                      );
                    }}
                  />
                  <Scatter data={scatterData} fill="rgb(109 94 15)" />
                </ScatterChart>
              </ResponsiveContainer>
            ) : (
              <div className="text-center py-12 text-on-surface-variant">
                No interventions match the current filter
              </div>
            )}
          </div>

          {/* Intervention table */}
          <div className="bg-surface-container-lowest rounded-xl border border-outline-variant overflow-hidden">
            <div className="px-6 py-4 border-b border-outline-variant">
              <h3 className="font-semibold font-heading text-on-surface">All Interventions</h3>
            </div>
            <div className="overflow-y-auto max-h-96">
              <table className="w-full">
                <thead className="sticky top-0">
                  <tr className="bg-surface-container text-left text-xs font-medium text-on-surface-variant uppercase">
                    <th className="px-6 py-3">Intervention</th>
                    <th className="px-6 py-3 text-right">Documents</th>
                    <th className="px-6 py-3 text-right">Sources</th>
                    <th className="px-6 py-3 text-right">Confidence</th>
                    <th className="px-6 py-3">Evidence</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-outline-variant">
                  {[...entries]
                    .sort((a, b) => b.confidence - a.confidence)
                    .map((i) => (
                      <tr key={i.name} className="hover:bg-surface-container-low">
                        <td className="px-6 py-3 text-sm font-medium text-on-surface capitalize">{i.name}</td>
                        <td className="px-6 py-3 text-sm text-on-surface text-right">{i.document_count}</td>
                        <td className="px-6 py-3 text-sm text-on-surface text-right">{i.source_types}</td>
                        <td className="px-6 py-3 text-sm text-right font-medium text-primary">
                          {i.confidence.toFixed(1)}
                        </td>
                        <td className="px-6 py-3">
                          <div className="w-24 h-2 bg-surface-variant rounded-full overflow-hidden">
                            <div
                              className="h-full bg-primary rounded-full"
                              style={{ width: `${Math.min(i.confidence, 100)}%` }}
                            />
                          </div>
                        </td>
                      </tr>
                    ))}
                </tbody>
              </table>
            </div>
          </div>
        </>
      )}

      {!loading && entries.length === 0 && (
        <div className="text-center py-20 text-on-surface-variant">
          <Map size={48} className="mx-auto mb-4 text-outline" />
          <p className="text-lg font-medium font-heading">No interventions found</p>
          <p className="text-sm mt-1">Is the API server running?</p>
        </div>
      )}
    </div>
  );
}
