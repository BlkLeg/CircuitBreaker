import React, { useState, useRef } from 'react';
import { NavLink } from 'react-router-dom';
import { X } from 'lucide-react';

const MobileOverflowSheet = ({ isOpen, onClose, navItems, pendingCount }) => {
  const [startY, setStartY] = useState(null);
  const [currentY, setCurrentY] = useState(null);
  const sheetRef = useRef(null);

  if (!isOpen) return null;

  const handleTouchStart = (e) => {
    setStartY(e.touches[0].clientY);
    setCurrentY(e.touches[0].clientY);
  };

  const handleTouchMove = (e) => {
    if (startY === null) return;
    const y = e.touches[0].clientY;
    setCurrentY(y);
    
    // Optional: add visual feedback by translating the sheet down
    if (y > startY && sheetRef.current) {
      sheetRef.current.style.transform = `translateY(${y - startY}px)`;
    }
  };

  const handleTouchEnd = () => {
    if (startY !== null && currentY !== null) {
      const deltaY = currentY - startY;
      if (deltaY > 50) {
        onClose();
      }
    }
    
    // Reset state & transform
    setStartY(null);
    setCurrentY(null);
    if (sheetRef.current) {
      sheetRef.current.style.transform = '';
    }
  };

  return (
    <div className="mobile-overflow-overlay" onClick={onClose}>
      <div 
        ref={sheetRef}
        className={`mobile-overflow-sheet ${isOpen ? 'open' : ''}`} 
        onClick={(e) => e.stopPropagation()}
        onTouchStart={handleTouchStart}
        onTouchMove={handleTouchMove}
        onTouchEnd={handleTouchEnd}
      >
        <div className="mobile-overflow-handle" />
        <div className="mobile-overflow-header">
          <h3>More</h3>
          <button onClick={onClose} className="mobile-overflow-close">
            <X size={20} />
          </button>
        </div>
        <div className="mobile-overflow-grid">
          {navItems.map((item) => (
            <NavLink
              key={item.path}
              to={item.path}
              className="mobile-overflow-item"
              onClick={onClose}
            >
              <div className="mobile-overflow-icon-wrapper">
                <item.icon size={24} strokeWidth={1.5} />
                {item.path === '/discovery' && pendingCount > 0 && (
                  <span className="mobile-overflow-badge">{pendingCount}</span>
                )}
              </div>
              <span>{item.label}</span>
            </NavLink>
          ))}
        </div>
      </div>
    </div>
  );
};

export default MobileOverflowSheet;
