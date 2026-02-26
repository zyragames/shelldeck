import React from 'react';
import { 
  MonitorUp, 
  FolderPlus, 
  Play, 
  Square, 
  RefreshCw, 
  Edit, 
  Settings, 
  Copy, 
  Eraser, 
  Search, 
  ChevronUp 
} from 'lucide-react';
import { Host } from '../types';

interface HomebarProps {
  onToggle: () => void;
  onNewHost: () => void;
  activeHost: Host | null;
}

export default function Homebar({ onToggle, onNewHost, activeHost }: HomebarProps) {
  return (
    <div className="h-12 bg-[#161b22] border-b border-[#30363d] flex items-center justify-between px-4 select-none">
      {/* Left - Main Actions */}
      <div className="flex items-center gap-1">
        <ActionButton icon={<MonitorUp className="w-4 h-4" />} label="New Host" onClick={onNewHost} />
        <ActionButton icon={<FolderPlus className="w-4 h-4" />} label="New Group" />
        <div className="w-px h-5 bg-[#30363d] mx-2" />
        <ActionButton icon={<Play className="w-4 h-4" />} label="Connect" disabled={!activeHost || activeHost.status === 'connected'} />
        <ActionButton icon={<Square className="w-4 h-4" />} label="Disconnect" disabled={!activeHost || activeHost.status !== 'connected'} />
        <ActionButton icon={<RefreshCw className="w-4 h-4" />} label="Reconnect" disabled={!activeHost} />
        <div className="w-px h-5 bg-[#30363d] mx-2" />
        <ActionButton icon={<Edit className="w-4 h-4" />} label="Edit" disabled={!activeHost} />
        <ActionButton icon={<Settings className="w-4 h-4" />} label="Settings" />
      </div>

      {/* Center - Context Actions */}
      <div className="flex items-center gap-1 opacity-80">
        {activeHost && (
          <>
            <ActionButton icon={<Copy className="w-4 h-4" />} label="Copy SSH" />
            <ActionButton icon={<Eraser className="w-4 h-4" />} label="Clear" />
            <ActionButton icon={<RefreshCw className="w-4 h-4" />} label="Reconnect" />
          </>
        )}
      </div>

      {/* Right - Utility */}
      <div className="flex items-center gap-3">
        <div className="relative group cursor-pointer">
          <Search className="w-4 h-4 text-gray-400 group-hover:text-white transition-colors" />
        </div>
        
        <div className="flex items-center gap-2 px-2 py-1 rounded-md bg-[#0d1117] border border-[#30363d]" title="SSH Agent Status">
          <div className="w-2 h-2 rounded-full bg-emerald-500 shadow-[0_0_8px_rgba(16,185,129,0.6)]" />
          <span className="text-xs font-mono text-gray-400">Agent</span>
        </div>

        <button onClick={onToggle} className="p-1.5 rounded-md hover:bg-[#21262d] text-gray-400 transition-colors" title="Collapse Homebar">
          <ChevronUp className="w-4 h-4" />
        </button>
      </div>
    </div>
  );
}

function ActionButton({ icon, label, disabled, onClick }: { icon: React.ReactNode, label: string, disabled?: boolean, onClick?: () => void }) {
  return (
    <button 
      onClick={onClick}
      disabled={disabled}
      className={`flex items-center gap-2 px-2.5 py-1.5 rounded-md text-sm transition-colors ${
        disabled 
          ? 'text-gray-600 cursor-not-allowed' 
          : 'text-gray-300 hover:bg-[#21262d] hover:text-white'
      }`}
      title={label}
    >
      {icon}
      <span className="hidden xl:inline">{label}</span>
    </button>
  );
}
