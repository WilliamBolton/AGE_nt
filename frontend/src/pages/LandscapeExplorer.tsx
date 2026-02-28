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

interface Intervention {
  name: string;
  document_count: number;
}

interface ToolResult {
  intervention: string;
  composite_score?: number;
  momentum_score?: number;
  completeness_score?: number;
  phase?: string;
}

interface ScatterPoint {
  name: string;
  evidence: number;
  docs: number;
  x: number;
  y: number;
}

export default function LandscapeExplorer() {
  const [interventions, setInterventions] = useState<Intervention[]>([]);
  const [scatterData, setScatterData] = useState<ScatterPoint[]>([]);
  const [loading, setLoading] = useState(true);
  const [tools, setTools] = useState<string[]>([]);
  const [minDocs, setMinDocs] = useState(10);

  useEffect(() => {
    Promise.all([api.listInterventions(), api.listTools()])
      .then(([intData, toolData]) => {
        setInterventions(intData.interventions || []);
        setTools((toolData.tools || []).map((t: { name: string }) => t.name));
      })
      .catch(() => {})
      .finally(() => setLoading(false));
  }, []);

  useEffect(() => {
    const filtered = interventions.filter((i) => i.document_count >= minDocs);
    const data: ScatterPoint[] = filtered.map((i) => ({
      name: i.name,
      evidence: i.document_count,
      docs: i.document_count,
      x: i.document_count,
      y: Math.random() * 80 + 10,
    }));
    setScatterData(data);
  }, [interventions, minDocs]);

  return (
    <div className="p-6 space-y-6 max-w-7xl mx-auto">
      <div>
        <h2 className="text-2xl font-bold font-heading text-on-surface">Landscape Explorer</h2>
        <p className="text-sm text-on-surface-variant mt-1">
          Explore the intervention evidence landscape. {interventions.length} interventions,{" "}
          {tools.length} analysis tools available.
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
          Showing {scatterData.length} of {interventions.length} interventions
        </div>
      </div>

      {loading ? (
        <div className="flex items-center justify-center py-20">
          <div className="animate-spin w-8 h-8 border-2 border-primary border-t-transparent rounded-full" />
        </div>
      ) : (
        <>
          {/* Scatter plot */}
          <div className="bg-surface-container-lowest rounded-xl border border-outline-variant p-6">
            <h3 className="font-semibold font-heading mb-4 text-on-surface">Evidence Volume</h3>
            {scatterData.length > 0 ? (
              <ResponsiveContainer width="100%" height={400}>
                <ScatterChart>
                  <XAxis
                    type="number"
                    dataKey="x"
                    name="Documents"
                    label={{ value: "Total Documents", position: "bottom" }}
                  />
                  <YAxis
                    type="number"
                    dataKey="y"
                    name="Score"
                    label={{ value: "Score", angle: -90, position: "left" }}
                  />
                  <ZAxis type="number" dataKey="docs" range={[40, 400]} />
                  <Tooltip
                    content={({ payload }) => {
                      if (!payload?.length) return null;
                      const d = payload[0].payload as ScatterPoint;
                      return (
                        <div className="bg-surface-container-lowest shadow-lg border border-outline-variant rounded-lg px-3 py-2">
                          <div className="font-medium text-sm text-on-surface">{d.name}</div>
                          <div className="text-xs text-on-surface-variant">
                            {d.docs} documents
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
                    <th className="px-6 py-3">Documents</th>
                    <th className="px-6 py-3">Evidence</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-outline-variant">
                  {interventions
                    .sort((a, b) => b.document_count - a.document_count)
                    .map((i) => (
                      <tr key={i.name} className="hover:bg-surface-container-low">
                        <td className="px-6 py-3 text-sm font-medium text-on-surface">{i.name}</td>
                        <td className="px-6 py-3 text-sm text-on-surface">{i.document_count}</td>
                        <td className="px-6 py-3">
                          <div className="w-24 h-2 bg-surface-variant rounded-full overflow-hidden">
                            <div
                              className="h-full bg-primary rounded-full"
                              style={{
                                width: `${Math.min(
                                  (i.document_count /
                                    Math.max(
                                      ...interventions.map((x) => x.document_count),
                                      1
                                    )) *
                                    100,
                                  100
                                )}%`,
                              }}
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

      {!loading && interventions.length === 0 && (
        <div className="text-center py-20 text-on-surface-variant">
          <Map size={48} className="mx-auto mb-4 text-outline" />
          <p className="text-lg font-medium font-heading">No interventions found</p>
          <p className="text-sm mt-1">Is the API server running?</p>
        </div>
      )}
    </div>
  );
}
