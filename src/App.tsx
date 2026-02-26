import { useState } from 'react';
import { Host, Group, Tab } from './types';
import Sidebar from './components/Sidebar';
import Homebar from './components/Homebar';
import TabsView from './components/TabsView';
import Terminal from './components/Terminal';
import HostEditor from './components/HostEditor';

const INITIAL_GROUPS: Group[] = [
  { id: 'g1', name: 'Production', isExpanded: true },
  { id: 'g2', name: 'Staging', isExpanded: true },
  { id: 'g3', name: 'Lab', isExpanded: false },
];

const INITIAL_HOSTS: Host[] = [
  { id: 'h1', name: 'web-prod-01', hostname: '10.0.1.10', user: 'deploy', port: 22, groupId: 'g1', status: 'connected' },
  { id: 'h2', name: 'db-prod-01', hostname: '10.0.1.20', user: 'admin', port: 2222, groupId: 'g1', status: 'idle' },
  { id: 'h3', name: 'web-stage-01', hostname: '10.0.2.10', user: 'deploy', port: 22, groupId: 'g2', status: 'idle' },
  { id: 'h4', name: 'labvm01', hostname: '192.168.1.100', user: 'root', port: 22, groupId: 'g3', status: 'error' },
  { id: 'h5', name: 'router-home', hostname: '192.168.0.1', user: 'admin', port: 22, status: 'idle' },
];

export default function App() {
  const [groups, setGroups] = useState<Group[]>(INITIAL_GROUPS);
  const [hosts, setHosts] = useState<Host[]>(INITIAL_HOSTS);
  const [tabs, setTabs] = useState<Tab[]>([
    { id: 't1', hostId: 'h1', isActive: true }
  ]);
  
  const [isSidebarOpen, setIsSidebarOpen] = useState(true);
  const [isSidebarPinned, setIsSidebarPinned] = useState(true);
  const [isHomebarOpen, setIsHomebarOpen] = useState(true);
  
  const [isEditorOpen, setIsEditorOpen] = useState(false);
  const [editingHost, setEditingHost] = useState<Host | null>(null);

  const activeTab = tabs.find(t => t.isActive);
  const activeHost = activeTab ? hosts.find(h => h.id === activeTab.hostId) : null;

  const handleToggleGroup = (groupId: string) => {
    setGroups(groups.map(g => g.id === groupId ? { ...g, isExpanded: !g.isExpanded } : g));
  };

  const handleConnect = (hostId: string) => {
    // If already open, just switch to it
    const existingTab = tabs.find(t => t.hostId === hostId);
    if (existingTab) {
      setTabs(tabs.map(t => ({ ...t, isActive: t.id === existingTab.id })));
    } else {
      const newTab: Tab = { id: `t${Date.now()}`, hostId, isActive: true };
      setTabs([...tabs.map(t => ({ ...t, isActive: false })), newTab]);
    }
    
    // Simulate connection
    setHosts(hosts.map(h => h.id === hostId ? { ...h, status: 'connected' } : h));
  };

  const handleCloseTab = (tabId: string) => {
    const newTabs = tabs.filter(t => t.id !== tabId);
    if (newTabs.length > 0 && tabs.find(t => t.id === tabId)?.isActive) {
      newTabs[newTabs.length - 1].isActive = true;
    }
    setTabs(newTabs);
  };

  const handleSelectTab = (tabId: string) => {
    setTabs(tabs.map(t => ({ ...t, isActive: t.id === tabId })));
  };

  const handleNewHost = () => {
    setEditingHost(null);
    setIsEditorOpen(true);
  };

  const handleEditHost = (host: Host) => {
    setEditingHost(host);
    setIsEditorOpen(true);
  };

  const handleSaveHost = (host: Host) => {
    if (editingHost) {
      setHosts(hosts.map(h => h.id === host.id ? host : h));
    } else {
      setHosts([...hosts, { ...host, id: `h${Date.now()}`, status: 'idle' }]);
    }
    setIsEditorOpen(false);
  };

  return (
    <div className="flex h-screen w-full bg-[#0d1117] text-gray-300 font-sans overflow-hidden selection:bg-emerald-500/30">
      {/* Sidebar */}
      <Sidebar 
        isOpen={isSidebarOpen}
        isPinned={isSidebarPinned}
        onToggle={() => setIsSidebarOpen(!isSidebarOpen)}
        onTogglePin={() => setIsSidebarPinned(!isSidebarPinned)}
        groups={groups}
        hosts={hosts}
        onToggleGroup={handleToggleGroup}
        onConnect={handleConnect}
        onNewHost={handleNewHost}
        onEditHost={handleEditHost}
      />

      {/* Main Content */}
      <div className="flex flex-col flex-1 min-w-0 overflow-hidden">
        {isHomebarOpen && (
          <Homebar 
            onToggle={() => setIsHomebarOpen(false)}
            onNewHost={handleNewHost}
            activeHost={activeHost}
          />
        )}
        
        {!isHomebarOpen && (
          <div className="h-1 w-full bg-[#161b22] hover:bg-[#21262d] cursor-pointer" onClick={() => setIsHomebarOpen(true)} title="Expand Homebar" />
        )}

        <div className="flex flex-col flex-1 min-h-0">
          {tabs.length > 0 && (
            <TabsView 
              tabs={tabs} 
              hosts={hosts} 
              onSelect={handleSelectTab} 
              onClose={handleCloseTab} 
            />
          )}
          
          <div className="flex-1 relative bg-[#0a0c10]">
            {activeHost ? (
              <Terminal host={activeHost} />
            ) : (
              <div className="absolute inset-0 flex flex-col items-center justify-center text-center">
                <div className="w-24 h-24 mb-6 rounded-2xl bg-gradient-to-br from-emerald-500/20 to-emerald-900/20 flex items-center justify-center border border-emerald-500/20 shadow-[0_0_40px_rgba(16,185,129,0.1)]">
                  <svg className="w-12 h-12 text-emerald-500" fill="none" viewBox="0 0 24 24" stroke="currentColor">
                    <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5} d="M8 9l3 3-3 3m5 0h3M5 20h14a2 2 0 002-2V6a2 2 0 00-2-2H5a2 2 0 00-2 2v12a2 2 0 002 2z" />
                  </svg>
                </div>
                <h2 className="text-2xl font-semibold text-white mb-2 tracking-tight">ShellDeck</h2>
                <p className="text-gray-500 mb-8">Select a host or press <kbd className="px-2 py-1 bg-[#161b22] rounded text-xs border border-gray-800 mx-1 font-mono">Ctrl+K</kbd> to connect</p>
                
                <div className="flex gap-4">
                  <button 
                    onClick={handleNewHost}
                    className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white rounded-md font-medium transition-colors shadow-sm flex items-center gap-2"
                  >
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M12 4v16m8-8H4" /></svg>
                    New Host
                  </button>
                  <button className="px-4 py-2 bg-[#21262d] hover:bg-[#30363d] text-gray-300 rounded-md font-medium transition-colors border border-gray-700/50 flex items-center gap-2">
                    <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor"><path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-8l-4-4m0 0L8 8m4-4v12" /></svg>
                    Import SSH Config
                  </button>
                </div>
              </div>
            )}
          </div>
        </div>
      </div>

      {isEditorOpen && (
        <HostEditor 
          host={editingHost} 
          groups={groups}
          onSave={handleSaveHost} 
          onClose={() => setIsEditorOpen(false)} 
        />
      )}
    </div>
  );
}
