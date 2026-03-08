import React from 'react';

function SearchBox({ value, onChange }) {
  return (
    <input
      className="filter-input"
      type="text"
      placeholder="Search..."
      value={value}
      onChange={(e) => onChange(e.target.value)}
    />
  );
}

export default SearchBox;
