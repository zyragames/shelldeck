import { Tab, Host } from '../types';
import { TerminalSquare, X } from 'lucide-react';

interface TabsViewProps {
  tabs: Tab[];
  hosts: Host[];
  onSelect: (tabId: string) => void;
  onClose: (tabId: string) => void;
}

export default function TabsView({ tabs, hosts, onSelect, onClose }: TabsViewProps) {
  return (
    <div className="flex bg-[#0d1117] overflow-x-auto custom-scrollbar pt-2 px-2 gap-1 border-b border-[#30363d]">
      {tabs.map(tab => {
        const host = hosts.find(h => h.id === tab.hostId);
        if (!host) return null;

        return (
          <div
            key={tab.id}
            onClick={() => onSelect(tab.id)}
            className={`group flex items-center gap-2 px-3 py-2 min-w-[140px] max-w-[200px] border-t border-x rounded-t-lg cursor-pointer select-none transition-colors ${
              tab.isActive 
                ? 'bg-[#161b22] border-[#30363d] text-white' 
                : 'bg-transparent border-transparent text-gray-400 hover:bg-[#161b22]/50 hover:text-gray-300'
            }`}
          >
            <div className="relative flex-shrink-0">
              <TerminalSquare className={`w-4 h-4 ${tab.isActive ? 'text-emerald-500' : 'text-gray-500'}`} />
              <div className={`absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full border border-[#161b22] ${
                host.status === 'connected' ? 'bg-emerald-500' : 
                host.status === 'error' ? 'bg-red-500' : 'bg-gray-500'
              }`} />
            </div>
            
            <span className="text-sm truncate flex-1">{host.name}</span>
            
            <button 
              onClick={(e) => { e.stopPropagation(); onClose(tab.id); }}
              className={`p-0.5 rounded-md hover:bg-[#30363d] ${tab.isActive ? 'opacity-100' : 'opacity-0 group-hover:opacity-100'}`}
            >
              <X className="w-3.5 h-3.5" />
            </button>
            
            {tab.isActive && (
              <div className="absolute bottom-0 left-0 w-full h-[2px] bg-emerald-500" />
            )}
          </div>
        );
      })}
    </div>
  );
}
