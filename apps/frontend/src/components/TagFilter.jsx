import React from 'react';

function TagFilter({ value, onChange }) {
  return (
    <input
      className="filter-input"
      type="text"
      placeholder="Filter by tag..."
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

export default TagFilter;
