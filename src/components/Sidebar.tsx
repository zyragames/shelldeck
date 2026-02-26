import { Host, Group } from '../types';
import { 
  ChevronLeft, 
  Pin, 
  Search, 
  Folder, 
  FolderOpen, 
  TerminalSquare, 
  Plus, 
  MoreVertical,
  Terminal
} from 'lucide-react';
import { useState } from 'react';

interface SidebarProps {
  isOpen: boolean;
  isPinned: boolean;
  onToggle: () => void;
  onTogglePin: () => void;
  groups: Group[];
  hosts: Host[];
  onToggleGroup: (groupId: string) => void;
  onConnect: (hostId: string) => void;
  onNewHost: () => void;
  onEditHost: (host: Host) => void;
}

export default function Sidebar({
  isOpen,
  isPinned,
  onToggle,
  onTogglePin,
  groups,
  hosts,
  onToggleGroup,
  onConnect,
  onNewHost,
  onEditHost
}: SidebarProps) {
  const [searchQuery, setSearchQuery] = useState('');

  if (!isOpen) {
    return (
      <div className="w-12 bg-[#161b22] border-r border-[#30363d] flex flex-col items-center py-4 gap-4">
        <button onClick={onToggle} className="p-2 hover:bg-[#21262d] rounded-md text-gray-400 hover:text-white transition-colors" title="Expand Sidebar">
          <Terminal className="w-5 h-5" />
        </button>
        <div className="w-8 h-px bg-[#30363d]" />
        <button onClick={onNewHost} className="p-2 hover:bg-[#21262d] rounded-md text-emerald-500 transition-colors" title="New Host">
          <Plus className="w-5 h-5" />
        </button>
      </div>
    );
  }

  const filteredHosts = hosts.filter(h => 
    h.name.toLowerCase().includes(searchQuery.toLowerCase()) || 
    h.hostname.toLowerCase().includes(searchQuery.toLowerCase()) ||
    h.tags?.some(t => t.toLowerCase().includes(searchQuery.toLowerCase()))
  );

  const renderHost = (host: Host) => (
    <div 
      key={host.id}
      onDoubleClick={() => onConnect(host.id)}
      className="group flex items-center gap-2 px-2 py-1.5 mx-2 rounded-md hover:bg-[#21262d] cursor-pointer text-sm"
    >
      <div className="relative flex-shrink-0">
        <TerminalSquare className="w-4 h-4 text-gray-400 group-hover:text-gray-300" />
        <div className={`absolute -bottom-0.5 -right-0.5 w-2 h-2 rounded-full border border-[#161b22] ${
          host.status === 'connected' ? 'bg-emerald-500' : 
          host.status === 'error' ? 'bg-red-500' : 'bg-gray-500'
        }`} />
      </div>
      <div className="flex flex-col min-w-0 flex-1">
        <span className="text-gray-200 truncate">{host.name}</span>
        <span className="text-xs text-gray-500 truncate font-mono">{host.user}@{host.hostname}:{host.port}</span>
      </div>
      <button 
        onClick={(e) => { e.stopPropagation(); onEditHost(host); }}
        className="opacity-0 group-hover:opacity-100 p-1 hover:bg-[#30363d] rounded text-gray-400"
      >
        <MoreVertical className="w-3 h-3" />
      </button>
    </div>
  );

  return (
    <div className={`flex flex-col bg-[#161b22] border-r border-[#30363d] transition-all duration-200 ease-in-out ${isPinned ? 'w-[300px]' : 'w-[300px] absolute z-20 h-full shadow-2xl'}`}>
      {/* Header */}
      <div className="flex items-center justify-between px-4 py-3 border-b border-[#30363d]">
        <div className="flex items-center gap-2 text-white font-semibold tracking-tight">
          <Terminal className="w-5 h-5 text-emerald-500" />
          ShellDeck
        </div>
        <div className="flex items-center gap-1">
          <button onClick={onTogglePin} className={`p-1.5 rounded-md hover:bg-[#21262d] transition-colors ${isPinned ? 'text-emerald-500' : 'text-gray-400'}`} title="Pin Sidebar">
            <Pin className="w-4 h-4" />
          </button>
          <button onClick={onToggle} className="p-1.5 rounded-md hover:bg-[#21262d] text-gray-400 transition-colors" title="Collapse Sidebar">
            <ChevronLeft className="w-4 h-4" />
          </button>
        </div>
      </div>

      {/* Search */}
      <div className="p-3">
        <div className="relative">
          <Search className="absolute left-2.5 top-2 w-4 h-4 text-gray-500" />
          <input 
            type="text" 
            placeholder="Search hosts, groups, tags..." 
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="w-full bg-[#0d1117] border border-[#30363d] rounded-md py-1.5 pl-9 pr-3 text-sm text-gray-200 placeholder-gray-500 focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 transition-all"
          />
        </div>
      </div>

      {/* Tree View */}
      <div className="flex-1 overflow-y-auto py-2 custom-scrollbar">
        {searchQuery ? (
          <div className="space-y-0.5">
            {filteredHosts.map(renderHost)}
            {filteredHosts.length === 0 && (
              <div className="px-4 py-8 text-center text-sm text-gray-500">No hosts found.</div>
            )}
          </div>
        ) : (
          <div className="space-y-1">
            {groups.map(group => (
              <div key={group.id}>
                <div 
                  className="flex items-center gap-2 px-3 py-1.5 hover:bg-[#21262d] cursor-pointer text-sm text-gray-300 select-none"
                  onClick={() => onToggleGroup(group.id)}
                >
                  {group.isExpanded ? (
                    <FolderOpen className="w-4 h-4 text-blue-400" />
                  ) : (
                    <Folder className="w-4 h-4 text-blue-400" />
                  )}
                  <span className="font-medium">{group.name}</span>
                </div>
                {group.isExpanded && (
                  <div className="pl-4 space-y-0.5 border-l border-[#30363d] ml-5 my-1">
                    {hosts.filter(h => h.groupId === group.id).map(renderHost)}
                  </div>
                )}
              </div>
            ))}
            
            {/* Ungrouped hosts */}
            <div className="mt-4 space-y-0.5">
              {hosts.filter(h => !h.groupId).map(renderHost)}
            </div>
          </div>
        )}
      </div>

      {/* Footer Actions */}
      <div className="p-3 border-t border-[#30363d] flex gap-2">
        <button 
          onClick={onNewHost}
          className="flex-1 flex items-center justify-center gap-1.5 py-1.5 bg-[#21262d] hover:bg-[#30363d] border border-[#30363d] rounded-md text-sm text-gray-300 transition-colors"
        >
          <Plus className="w-4 h-4" /> Host
        </button>
        <button className="flex-1 flex items-center justify-center gap-1.5 py-1.5 bg-[#21262d] hover:bg-[#30363d] border border-[#30363d] rounded-md text-sm text-gray-300 transition-colors">
          <Plus className="w-4 h-4" /> Group
        </button>
      </div>
    </div>
  );
}
