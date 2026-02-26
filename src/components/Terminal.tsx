import { useEffect, useRef, useState } from 'react';
import { Host } from '../types';

interface TerminalProps {
  host: Host;
}

export default function Terminal({ host }: TerminalProps) {
  const terminalRef = useRef<HTMLDivElement>(null);
  const [lines, setLines] = useState<string[]>([]);

  useEffect(() => {
    // Simulate terminal boot sequence
    setLines([
      `Connecting to ${host.user}@${host.hostname}:${host.port}...`,
      `Welcome to Ubuntu 22.04.3 LTS (GNU/Linux 5.15.0-82-generic x86_64)`,
      ``,
      ` * Documentation:  https://help.ubuntu.com`,
      ` * Management:     https://landscape.canonical.com`,
      ` * Support:        https://ubuntu.com/advantage`,
      ``,
      `System information as of ${new Date().toUTCString()}`,
      ``,
      `  System load:  0.01               Processes:             112`,
      `  Usage of /:   24.5% of 48.97GB   Users logged in:       1`,
      `  Memory usage: 12%                IPv4 address for eth0: ${host.hostname}`,
      `  Swap usage:   0%`,
      ``,
      `Last login: ${new Date(Date.now() - 86400000).toUTCString()} from 192.168.1.50`,
      `${host.user}@${host.name}:~$ `
    ]);
  }, [host]);

  return (
    <div className="absolute inset-0 bg-[#0a0c10] p-4 font-mono text-[13px] leading-relaxed text-gray-300 overflow-y-auto custom-scrollbar">
      {lines.map((line, i) => (
        <div key={i} className="whitespace-pre-wrap break-all">
          {line.includes('~$') ? (
            <span>
              <span className="text-emerald-400 font-bold">{host.user}@{host.name}</span>
              <span className="text-gray-300">:</span>
              <span className="text-blue-400 font-bold">~</span>
              <span className="text-gray-300">$ </span>
              <span className="animate-pulse bg-gray-400 w-2 h-4 inline-block align-middle" />
            </span>
          ) : (
            line
          )}
        </div>
      ))}
    </div>
  );
}
