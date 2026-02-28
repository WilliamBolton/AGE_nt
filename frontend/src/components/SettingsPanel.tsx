import { useState } from "react";
import { X } from "lucide-react";
import { getApiKey, setApiKey } from "../lib/settings";

export default function SettingsPanel({ onClose }: { onClose: () => void }) {
  const [key, setKey] = useState(getApiKey());
  const [saved, setSaved] = useState(false);

  const handleSave = () => {
    setApiKey(key);
    setSaved(true);
    setTimeout(() => setSaved(false), 2000);
  };

  return (
    <div className="fixed inset-0 bg-black/50 flex items-center justify-center z-50">
      <div className="bg-surface-container-lowest rounded-xl shadow-xl p-6 w-full max-w-md mx-4">
        <div className="flex justify-between items-center mb-4">
          <h2 className="text-lg font-semibold font-heading text-on-surface">Settings</h2>
          <button onClick={onClose} className="p-1 hover:bg-surface-variant rounded">
            <X size={20} className="text-on-surface-variant" />
          </button>
        </div>

        <div className="space-y-4">
          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1">
              Gemini API Key
            </label>
            <input
              type="password"
              value={key}
              onChange={(e) => setKey(e.target.value)}
              placeholder="Enter your Gemini API key..."
              className="w-full px-3 py-2 border border-outline-variant rounded-lg text-sm bg-surface text-on-surface focus:ring-2 focus:ring-primary focus:border-primary outline-none"
            />
            <p className="mt-1.5 text-xs text-on-surface-variant">
              Key is stored locally and sent per-request. Never stored on the server.
            </p>
          </div>

          <div>
            <label className="block text-sm font-medium text-on-surface-variant mb-1">
              API Server
            </label>
            <input
              type="text"
              value={import.meta.env.VITE_API_URL || "http://localhost:8000 (via proxy)"}
              disabled
              className="w-full px-3 py-2 border border-outline-variant rounded-lg text-sm bg-surface-container text-on-surface-variant"
            />
          </div>

          <button
            onClick={handleSave}
            className="w-full py-2 bg-primary text-on-primary rounded-lg text-sm font-medium hover:opacity-90 transition-opacity"
          >
            {saved ? "Saved!" : "Save"}
          </button>
        </div>
      </div>
    </div>
  );
}
