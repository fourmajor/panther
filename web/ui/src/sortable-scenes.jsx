import React from 'react';
import {DndContext,closestCenter,KeyboardSensor,MouseSensor,TouchSensor,useSensor,useSensors} from '@dnd-kit/core';
import {SortableContext,useSortable,sortableKeyboardCoordinates,rectSortingStrategy,arrayMove} from '@dnd-kit/sortable';
import {CSS} from '@dnd-kit/utilities';
import {GripVertical} from 'lucide-react';
import {Button} from './components/ui/button.jsx';

function Scene({scene,index,selected,disabled,onSelect}) {
 const {attributes,listeners,setNodeRef,setActivatorNodeRef,transform,transition,isDragging}=useSortable({id:scene.id,disabled});
 return <div ref={setNodeRef} className="scene-order-row" data-dragging={isDragging?'true':undefined} style={{transform:CSS.Transform.toString(transform),transition}}>
  <Button variant="ghost" size="icon" ref={setActivatorNodeRef} type="button" className="scene-drag-handle" aria-label={`Reorder ${scene.name}`} title="Drag to reorder" disabled={disabled} {...attributes} {...listeners}><GripVertical size={16} aria-hidden="true"/></Button>
  <Button variant="ghost" type="button" className="scene-card" aria-label={scene.name} aria-pressed={selected} data-order={`${index+1}.`} onClick={()=>onSelect(scene)}>{scene.name}</Button>
  <small>{scene.selectedOutputKey?'Ready':scene.type&&scene.type!=='general'?scene.type[0].toUpperCase()+scene.type.slice(1):'Not rendered'}</small>
 </div>;
}
export function SortableScenes({items,selectedId,disabled,onSelect,onReorder}) {
 const sensors=useSensors(useSensor(MouseSensor,{activationConstraint:{distance:6}}),useSensor(TouchSensor,{activationConstraint:{delay:150,tolerance:5}}),useSensor(KeyboardSensor,{coordinateGetter:sortableKeyboardCoordinates}));
 return <DndContext sensors={sensors} collisionDetection={closestCenter} onDragEnd={({active,over})=>{if(!disabled&&over&&active.id!==over.id)onReorder(arrayMove(items,items.findIndex(item=>item.id===active.id),items.findIndex(item=>item.id===over.id)).map(item=>item.id));}} accessibility={{screenReaderInstructions:{draggable:'Press space to pick up a scene. Use arrow keys to move it, space to drop, or escape to cancel.'}}}>
  <SortableContext items={items.map(item=>item.id)} strategy={rectSortingStrategy}>{items.map((scene,index)=><Scene key={scene.id} scene={scene} index={index} selected={selectedId===scene.id} disabled={disabled} onSelect={onSelect}/>)}</SortableContext>
 </DndContext>;
}
