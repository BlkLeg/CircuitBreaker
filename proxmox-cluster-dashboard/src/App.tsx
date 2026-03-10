import React, { useState, useEffect } from 'react';
import { 
  Server, Activity, AlertTriangle, CheckCircle, 
  Clock, Database, HardDrive, Network, Cpu, 
  Settings, User, HelpCircle, LogOut, ChevronRight,
  Maximize2, RefreshCw
} from 'lucide-react';
import { 
  LineChart, Line, AreaChart, Area, XAxis, YAxis, 
  CartesianGrid, Tooltip, ResponsiveContainer, 
  PieChart, Pie, Cell, Legend
} from 'recharts';
import Plot from 'react-plotly.js';

// --- DUMMY DATA ---

const clusterStatus = {
  name: "pve-cluster-01",
  nodes: 3,
  vms: 42,
  lxc: 15,
  quorum: true,
  uptime: "45d 12h 30m"
};

const problems = [
  { id: 1, time: "10:24:15", severity: "High", host: "pve-node-02", problem: "CPU load is too high (over 90% for 5m)", status: "PROBLEM" },
  { id: 2, time: "09:15:00", severity: "Warning", host: "pve-node-01", problem: "Storage /var/lib/vz is over 80% full", status: "PROBLEM" },
  { id: 3, time: "08:30:22", severity: "Info", host: "pve-cluster-01", problem: "Backup job 'daily-vms' completed with warnings", status: "RESOLVED" },
];

const cpuData = Array.from({ length: 20 }).map((_, i) => ({
  time: `10:${i.toString().padStart(2, '0')}`,
  'pve-node-01': Math.random() * 30 + 20,
  'pve-node-02': Math.random() * 40 + 50,
  'pve-node-03': Math.random() * 20 + 10,
}));

const networkData = Array.from({ length: 20 }).map((_, i) => ({
  time: `10:${i.toString().padStart(2, '0')}`,
  in: Math.random() * 500 + 100,
  out: Math.random() * 300 + 50,
}));

const storageData = [
  { name: 'local-lvm', value: 850, fill: '#2f7ed8' },
  { name: 'local', value: 150, fill: '#0d233a' },
  { name: 'ceph-pool', value: 2500, fill: '#8bbc21' },
  { name: 'nfs-backup', value: 4000, fill: '#910000' },
];

// --- COMPONENTS ---

const Widget = ({ title, children, className = "" }) => (
  <div className={`bg-[#ffffff] dark:bg-[#0a1017] border border-[#d3d3d3] dark:border-[#2b3643] flex flex-col ${className}`}>
    <div className="flex items-center justify-between px-3 py-2 bg-[#f9f9f9] dark:bg-[#15202b] border-b border-[#d3d3d3] dark:border-[#2b3643]">
      <h3 className="text-sm font-bold text-[#333] dark:text-[#e1e3ed]">{title}</h3>
      <div className="flex gap-2 text-[#768d99]">
        <RefreshCw size={14} className="cursor-pointer hover:text-[#0275b8]" />
        <Maximize2 size={14} className="cursor-pointer hover:text-[#0275b8]" />
      </div>
    </div>
    <div className="p-3 flex-1 overflow-auto text-sm text-[#333] dark:text-[#e1e3ed]">
      {children}
    </div>
  </div>
);

const StatusBadge = ({ status }) => {
  const colors = {
    OK: "bg-[#59db8f] text-white",
    PROBLEM: "bg-[#e45959] text-white",
    RESOLVED: "bg-[#59db8f] text-white",
    High: "bg-[#e45959] text-white",
    Warning: "bg-[#ffc859] text-black",
    Info: "bg-[#7499ff] text-white"
  };
  return (
    <span className={`px-2 py-0.5 text-xs font-bold rounded-sm ${colors[status] || "bg-gray-500 text-white"}`}>
      {status}
    </span>
  );
};

// --- MAIN APP ---

export default function App() {
  const [darkMode, setDarkMode] = useState(true);

  useEffect(() => {
    if (darkMode) {
      document.documentElement.classList.add('dark');
    } else {
      document.documentElement.classList.remove('dark');
    }
  }, [darkMode]);

  return (
    <div className="min-h-screen bg-[#ebebeb] dark:bg-[#02060b] text-[#333] dark:text-[#e1e3ed] font-sans flex flex-col">
      {/* Top Navigation - Zabbix Style */}
      <header className="bg-[#0275b8] dark:bg-[#02060b] border-b border-[#0275b8] dark:border-[#2b3643] text-white flex items-center justify-between px-4 py-2">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2 font-bold text-lg tracking-wider">
            <Server size={20} className="text-[#59db8f]" />
            <span>ZABBIX</span>
          </div>
          <nav className="hidden md:flex gap-4 text-sm font-medium">
            <a href="#" className="text-white border-b-2 border-white pb-1">Monitoring</a>
            <a href="#" className="text-[#b3dcf2] dark:text-[#768d99] hover:text-white pb-1">Services</a>
            <a href="#" className="text-[#b3dcf2] dark:text-[#768d99] hover:text-white pb-1">Inventory</a>
            <a href="#" className="text-[#b3dcf2] dark:text-[#768d99] hover:text-white pb-1">Reports</a>
            <a href="#" className="text-[#b3dcf2] dark:text-[#768d99] hover:text-white pb-1">Configuration</a>
            <a href="#" className="text-[#b3dcf2] dark:text-[#768d99] hover:text-white pb-1">Administration</a>
          </nav>
        </div>
        <div className="flex items-center gap-4 text-sm">
          <div className="flex items-center gap-2 text-[#b3dcf2] dark:text-[#768d99]">
            <input 
              type="text" 
              placeholder="Search" 
              className="bg-white/10 border border-white/20 rounded px-2 py-1 text-white placeholder-white/50 focus:outline-none focus:border-white/50 w-48"
            />
          </div>
          <button onClick={() => setDarkMode(!darkMode)} className="hover:text-[#b3dcf2]" title="Toggle Theme">
            <Settings size={18} />
          </button>
          <User size={18} className="hover:text-[#b3dcf2] cursor-pointer" />
          <HelpCircle size={18} className="hover:text-[#b3dcf2] cursor-pointer" />
          <LogOut size={18} className="hover:text-[#b3dcf2] cursor-pointer" />
        </div>
      </header>

      {/* Sub Navigation / Breadcrumbs */}
      <div className="bg-[#ffffff] dark:bg-[#0a1017] border-b border-[#d3d3d3] dark:border-[#2b3643] px-4 py-2 flex items-center justify-between text-sm">
        <div className="flex items-center gap-2">
          <span className="text-[#0275b8] font-medium cursor-pointer">All dashboards</span>
          <ChevronRight size={14} className="text-[#768d99]" />
          <span className="font-bold">Proxmox Cluster Overview</span>
        </div>
        <div className="flex items-center gap-4 text-[#768d99]">
          <span>Updated: 10:25:00</span>
          <button className="bg-[#0275b8] text-white px-3 py-1 rounded-sm hover:bg-[#0265a0] transition-colors">
            Edit dashboard
          </button>
        </div>
      </div>

      {/* Main Content Grid */}
      <main className="flex-1 p-2 md:p-4 grid grid-cols-1 md:grid-cols-12 gap-2 md:gap-4 overflow-auto">
        
        {/* Row 1 */}
        <Widget title="Cluster Status" className="md:col-span-3">
          <div className="flex flex-col gap-4">
            <div className="flex justify-between items-center border-b border-[#eee] dark:border-[#2b3643] pb-2">
              <span className="text-[#768d99]">Cluster Name</span>
              <span className="font-bold">{clusterStatus.name}</span>
            </div>
            <div className="flex justify-between items-center border-b border-[#eee] dark:border-[#2b3643] pb-2">
              <span className="text-[#768d99]">Quorum</span>
              <span className="text-[#59db8f] font-bold flex items-center gap-1">
                <CheckCircle size={14} /> OK
              </span>
            </div>
            <div className="flex justify-between items-center border-b border-[#eee] dark:border-[#2b3643] pb-2">
              <span className="text-[#768d99]">Nodes</span>
              <span className="font-bold">{clusterStatus.nodes} (3 online)</span>
            </div>
            <div className="flex justify-between items-center border-b border-[#eee] dark:border-[#2b3643] pb-2">
              <span className="text-[#768d99]">Guests (VM/LXC)</span>
              <span className="font-bold">{clusterStatus.vms} / {clusterStatus.lxc}</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-[#768d99]">Uptime</span>
              <span className="font-bold">{clusterStatus.uptime}</span>
            </div>
          </div>
        </Widget>

        <Widget title="Problems by severity" className="md:col-span-9">
          <table className="w-full text-left border-collapse">
            <thead>
              <tr className="border-b border-[#eee] dark:border-[#2b3643] text-[#768d99]">
                <th className="pb-2 font-normal">Time</th>
                <th className="pb-2 font-normal">Severity</th>
                <th className="pb-2 font-normal">Host</th>
                <th className="pb-2 font-normal">Problem</th>
                <th className="pb-2 font-normal">Status</th>
              </tr>
            </thead>
            <tbody>
              {problems.map(p => (
                <tr key={p.id} className="border-b border-[#eee] dark:border-[#2b3643] hover:bg-[#f4f4f4] dark:hover:bg-[#15202b] transition-colors">
                  <td className="py-2">{p.time}</td>
                  <td className="py-2"><StatusBadge status={p.severity} /></td>
                  <td className="py-2 font-medium text-[#0275b8] cursor-pointer">{p.host}</td>
                  <td className="py-2">{p.problem}</td>
                  <td className="py-2"><StatusBadge status={p.status} /></td>
                </tr>
              ))}
            </tbody>
          </table>
        </Widget>

        {/* Row 2 */}
        <Widget title="CPU Usage (Recharts)" className="md:col-span-6 h-80">
          <ResponsiveContainer width="100%" height="100%">
            <LineChart data={cpuData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={darkMode ? "#2b3643" : "#eee"} vertical={false} />
              <XAxis dataKey="time" stroke={darkMode ? "#768d99" : "#999"} tick={{fontSize: 12}} />
              <YAxis stroke={darkMode ? "#768d99" : "#999"} tick={{fontSize: 12}} domain={[0, 100]} />
              <Tooltip 
                contentStyle={{ backgroundColor: darkMode ? '#15202b' : '#fff', borderColor: darkMode ? '#2b3643' : '#ccc' }}
                itemStyle={{ color: darkMode ? '#e1e3ed' : '#333' }}
              />
              <Legend iconType="rect" wrapperStyle={{ fontSize: '12px' }} />
              <Line type="monotone" dataKey="pve-node-01" stroke="#59db8f" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="pve-node-02" stroke="#e45959" strokeWidth={2} dot={false} isAnimationActive={false} />
              <Line type="monotone" dataKey="pve-node-03" stroke="#7499ff" strokeWidth={2} dot={false} isAnimationActive={false} />
            </LineChart>
          </ResponsiveContainer>
        </Widget>

        <Widget title="Memory Usage (Plotly)" className="md:col-span-6 h-80">
          <div className="w-full h-full flex items-center justify-center -mt-4">
            <Plot
              data={[
                {
                  x: cpuData.map(d => d.time),
                  y: cpuData.map(d => d['pve-node-01'] * 0.8),
                  type: 'scatter',
                  mode: 'lines',
                  name: 'pve-node-01',
                  line: {color: '#59db8f', width: 2}
                },
                {
                  x: cpuData.map(d => d.time),
                  y: cpuData.map(d => d['pve-node-02'] * 0.6),
                  type: 'scatter',
                  mode: 'lines',
                  name: 'pve-node-02',
                  line: {color: '#ffc859', width: 2}
                },
                {
                  x: cpuData.map(d => d.time),
                  y: cpuData.map(d => d['pve-node-03'] * 0.9),
                  type: 'scatter',
                  mode: 'lines',
                  name: 'pve-node-03',
                  line: {color: '#7499ff', width: 2}
                }
              ]}
              layout={{
                autosize: true,
                margin: { l: 40, r: 20, t: 20, b: 30 },
                paper_bgcolor: 'rgba(0,0,0,0)',
                plot_bgcolor: 'rgba(0,0,0,0)',
                font: { color: darkMode ? '#768d99' : '#999', size: 12 },
                xaxis: { showgrid: false, zeroline: false },
                yaxis: { 
                  showgrid: true, 
                  gridcolor: darkMode ? '#2b3643' : '#eee',
                  zeroline: false,
                  range: [0, 100]
                },
                legend: { orientation: 'h', y: -0.2 }
              }}
              config={{ responsive: true, displayModeBar: false }}
              style={{ width: '100%', height: '100%' }}
            />
          </div>
        </Widget>

        {/* Row 3 */}
        <Widget title="Network Traffic (Recharts)" className="md:col-span-8 h-80">
          <ResponsiveContainer width="100%" height="100%">
            <AreaChart data={networkData} margin={{ top: 5, right: 20, bottom: 5, left: 0 }}>
              <CartesianGrid strokeDasharray="3 3" stroke={darkMode ? "#2b3643" : "#eee"} vertical={false} />
              <XAxis dataKey="time" stroke={darkMode ? "#768d99" : "#999"} tick={{fontSize: 12}} />
              <YAxis stroke={darkMode ? "#768d99" : "#999"} tick={{fontSize: 12}} />
              <Tooltip 
                contentStyle={{ backgroundColor: darkMode ? '#15202b' : '#fff', borderColor: darkMode ? '#2b3643' : '#ccc' }}
              />
              <Legend iconType="rect" wrapperStyle={{ fontSize: '12px' }} />
              <Area type="monotone" dataKey="in" stackId="1" stroke="#59db8f" fill="#59db8f" fillOpacity={0.6} isAnimationActive={false} name="Traffic In (Mbps)" />
              <Area type="monotone" dataKey="out" stackId="1" stroke="#7499ff" fill="#7499ff" fillOpacity={0.6} isAnimationActive={false} name="Traffic Out (Mbps)" />
            </AreaChart>
          </ResponsiveContainer>
        </Widget>

        <Widget title="Storage Pools" className="md:col-span-4 h-80">
          <ResponsiveContainer width="100%" height="100%">
            <PieChart>
              <Pie
                data={storageData}
                cx="50%"
                cy="45%"
                innerRadius={60}
                outerRadius={80}
                paddingAngle={2}
                dataKey="value"
                stroke="none"
                isAnimationActive={false}
              >
                {storageData.map((entry, index) => (
                  <Cell key={`cell-${index}`} fill={entry.fill} />
                ))}
              </Pie>
              <Tooltip 
                contentStyle={{ backgroundColor: darkMode ? '#15202b' : '#fff', borderColor: darkMode ? '#2b3643' : '#ccc', borderRadius: '4px' }}
                itemStyle={{ color: darkMode ? '#e1e3ed' : '#333' }}
                formatter={(value) => [`${value} GB`, 'Used']}
              />
              <Legend verticalAlign="bottom" height={36} iconType="circle" wrapperStyle={{ fontSize: '12px' }} />
            </PieChart>
          </ResponsiveContainer>
        </Widget>

      </main>
    </div>
  );
}
