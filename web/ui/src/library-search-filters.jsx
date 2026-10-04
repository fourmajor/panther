import React from 'react';
import {Search} from 'lucide-react';
import {Input} from './components/ui/input.jsx';
import {MultiSelect} from './components/ui/multi-select.jsx';

// Both libraries render this form; page code supplies only data and filtering callbacks.
export function LibrarySearchFilters({label,search,onSearch,tags=[],selectedTags=[],onTags,onCreateTag,characters=[],selectedCharacters=[],onCharacters}) {
  return <div className="library-search-filters grid w-full gap-3" aria-label={`${label} and filters`}>
    <label className="library-search-field"><span className="library-search-label">Search</span><Search size={18} aria-hidden="true"/><Input aria-label={label} type="search" placeholder={label} maxLength={300} value={search} onChange={event=>onSearch(event.target.value)}/></label>
    <div className="library-filter-fields">
      <div data-multi-filter="tags"><MultiSelect inlineLabel label="Tags" options={tags} value={selectedTags} onChange={onTags} onCreate={onCreateTag} placeholder="Add tag…"/></div>
      <div data-multi-filter="characters"><MultiSelect inlineLabel label="Characters" options={characters} value={selectedCharacters} onChange={onCharacters} placeholder="Add character…"/></div>
    </div>
  </div>;
}
