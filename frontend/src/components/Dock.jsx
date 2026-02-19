import React from 'react';
import { NavLink } from 'react-router-dom';
import { Cpu, Server, Layers, Network, ScrollText, Settings } from 'lucide-react';

const NAV = [
  { path: '/hardware',      icon: Cpu,        label: 'Hardware'  },
  { path: '/compute-units', icon: Server,     label: 'Compute'   },
  { path: '/services',      icon: Layers,     label: 'Services'  },
  { path: '/networks',      icon: Network,    label: 'Network'   },
  { path: '/logs',          icon: ScrollText, label: 'Logs'      },
  { path: '/settings',      icon: Settings,   label: 'Settings'  },
];

function DockItem({ path, icon: Icon, label }) {
  return (
    <NavLink
      to={path}
      className={({ isActive }) => `dock-item${isActive ? ' active' : ''}`}
    >
      <Icon size={22} strokeWidth={1.5} />
      <span>{label}</span>
    </NavLink>
  );
}

function Dock() {
  return (
    <nav className="dock">
      {NAV.map((item) => (
        <DockItem key={item.path} {...item} />
      ))}
    </nav>
  );
}

export default Dock;
