import React, { useState } from 'react';
import { Host, Group } from '../types';
import { X, Server, Shield, Tag, ChevronDown, ChevronRight } from 'lucide-react';

interface HostEditorProps {
  host: Host | null;
  groups: Group[];
  onSave: (host: Host) => void;
  onClose: () => void;
}

export default function HostEditor({ host, groups, onSave, onClose }: HostEditorProps) {
  const [formData, setFormData] = useState<Partial<Host>>(
    host || {
      name: '',
      hostname: '',
      user: 'root',
      port: 22,
      groupId: '',
      tags: [],
      identityFile: '',
      extraArgs: ''
    }
  );
  
  const [showAdvanced, setShowAdvanced] = useState(false);

  const handleChange = (e: React.ChangeEvent<HTMLInputElement | HTMLSelectElement>) => {
    const { name, value } = e.target;
    setFormData(prev => ({ 
      ...prev, 
      [name]: name === 'port' ? parseInt(value) || 22 : value 
    }));
  };

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!formData.name || !formData.hostname) return;
    
    onSave(formData as Host);
  };

  return (
    <div className="fixed inset-0 bg-black/50 backdrop-blur-sm z-50 flex items-center justify-center p-4">
      <div className="bg-[#161b22] border border-[#30363d] rounded-xl shadow-2xl w-full max-w-md overflow-hidden flex flex-col">
        
        {/* Header */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-[#30363d] bg-[#0d1117]">
          <h2 className="text-lg font-semibold text-white flex items-center gap-2">
            <Server className="w-5 h-5 text-emerald-500" />
            {host ? 'Edit Host' : 'New Host'}
          </h2>
          <button onClick={onClose} className="text-gray-400 hover:text-white transition-colors">
            <X className="w-5 h-5" />
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="flex-1 overflow-y-auto p-5 space-y-4 custom-scrollbar">
          
          <div className="space-y-1">
            <label className="text-xs font-medium text-gray-400 uppercase tracking-wider">Label</label>
            <input 
              autoFocus
              name="name"
              value={formData.name}
              onChange={handleChange}
              placeholder="e.g. web-prod-01"
              className="w-full bg-[#0d1117] border border-[#30363d] rounded-md px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
              required
            />
          </div>

          <div className="grid grid-cols-3 gap-4">
            <div className="col-span-2 space-y-1">
              <label className="text-xs font-medium text-gray-400 uppercase tracking-wider">Hostname / IP</label>
              <input 
                name="hostname"
                value={formData.hostname}
                onChange={handleChange}
                placeholder="10.0.0.1"
                className="w-full bg-[#0d1117] border border-[#30363d] rounded-md px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
                required
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-400 uppercase tracking-wider">Port</label>
              <input 
                name="port"
                type="number"
                value={formData.port}
                onChange={handleChange}
                className="w-full bg-[#0d1117] border border-[#30363d] rounded-md px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
              />
            </div>
          </div>

          <div className="grid grid-cols-2 gap-4">
            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-400 uppercase tracking-wider">User</label>
              <input 
                name="user"
                value={formData.user}
                onChange={handleChange}
                className="w-full bg-[#0d1117] border border-[#30363d] rounded-md px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
              />
            </div>
            <div className="space-y-1">
              <label className="text-xs font-medium text-gray-400 uppercase tracking-wider">Group</label>
              <select 
                name="groupId"
                value={formData.groupId || ''}
                onChange={handleChange}
                className="w-full bg-[#0d1117] border border-[#30363d] rounded-md px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500 appearance-none"
              >
                <option value="">None</option>
                {groups.map(g => (
                  <option key={g.id} value={g.id}>{g.name}</option>
                ))}
              </select>
            </div>
          </div>

          <div className="space-y-1">
            <label className="text-xs font-medium text-gray-400 uppercase tracking-wider flex items-center gap-1">
              <Tag className="w-3 h-3" /> Tags
            </label>
            <input 
              name="tags"
              value={formData.tags?.join(', ')}
              onChange={(e) => setFormData({...formData, tags: e.target.value.split(',').map(t => t.trim()).filter(Boolean)})}
              placeholder="prod, web, linux (comma separated)"
              className="w-full bg-[#0d1117] border border-[#30363d] rounded-md px-3 py-2 text-sm text-white focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
            />
          </div>

          {/* Advanced Section */}
          <div className="pt-2 border-t border-[#30363d]">
            <button 
              type="button"
              onClick={() => setShowAdvanced(!showAdvanced)}
              className="flex items-center gap-2 text-sm text-gray-400 hover:text-white transition-colors w-full"
            >
              {showAdvanced ? <ChevronDown className="w-4 h-4" /> : <ChevronRight className="w-4 h-4" />}
              Advanced Settings
            </button>
            
            {showAdvanced && (
              <div className="mt-4 space-y-4 animate-in slide-in-from-top-2 duration-200">
                <div className="space-y-1">
                  <label className="text-xs font-medium text-gray-400 uppercase tracking-wider flex items-center gap-1">
                    <Shield className="w-3 h-3" /> Identity File
                  </label>
                  <input 
                    name="identityFile"
                    value={formData.identityFile}
                    onChange={handleChange}
                    placeholder="~/.ssh/id_rsa"
                    className="w-full bg-[#0d1117] border border-[#30363d] rounded-md px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
                  />
                </div>
                <div className="space-y-1">
                  <label className="text-xs font-medium text-gray-400 uppercase tracking-wider">Extra SSH Args</label>
                  <input 
                    name="extraArgs"
                    value={formData.extraArgs}
                    onChange={handleChange}
                    placeholder="-A -X"
                    className="w-full bg-[#0d1117] border border-[#30363d] rounded-md px-3 py-2 text-sm text-white font-mono focus:outline-none focus:border-emerald-500 focus:ring-1 focus:ring-emerald-500"
                  />
                </div>
              </div>
            )}
          </div>
        </form>

        {/* Footer */}
        <div className="px-5 py-4 border-t border-[#30363d] bg-[#0d1117] flex justify-end gap-3">
          <button 
            type="button"
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-300 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button 
            type="submit"
            className="px-4 py-2 bg-emerald-600 hover:bg-emerald-500 text-white text-sm font-medium rounded-md transition-colors shadow-sm"
          >
            {host ? 'Save Changes' : 'Save Host'}
          </button>
        </div>
      </div>
    </div>
  );
}
