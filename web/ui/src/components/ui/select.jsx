import React from "react";
import * as Primitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";

// Radix primitives, styled with the shadcn Select composition. The popup is
// portalled so header overflow and small-screen navigation cannot clip it.
export function GameSelect({ games, value, disabled, onChange }) {
  return <Primitive.Root value={value || undefined} onValueChange={onChange} disabled={disabled}>
    <Primitive.Trigger id="game-select-trigger" aria-label="Current game" className="panther-select-trigger flex h-10 items-center justify-between gap-2 rounded-md border px-3 text-sm shadow-sm focus-visible:outline-none focus-visible:ring-2 disabled:cursor-not-allowed disabled:opacity-50">
      <Primitive.Value placeholder="Choose game" />
      <Primitive.Icon><ChevronDown className="h-4 w-4 opacity-60" aria-hidden="true" /></Primitive.Icon>
    </Primitive.Trigger>
    <Primitive.Portal>
      <Primitive.Content position="popper" sideOffset={6} className="panther-select-content z-50 max-h-80 min-w-48 overflow-y-auto rounded-md border p-1 shadow-lg">
        <Primitive.Viewport>
          {games.map(game => <Primitive.Item key={game.id} value={game.id} className="panther-select-item relative flex cursor-default select-none items-center rounded-sm py-2 pl-8 pr-3 text-sm outline-none">
            <Primitive.ItemIndicator className="absolute left-2"><Check className="h-4 w-4" aria-hidden="true" /></Primitive.ItemIndicator>
            <Primitive.ItemText>{game.name}</Primitive.ItemText>
          </Primitive.Item>)}
        </Primitive.Viewport>
      </Primitive.Content>
    </Primitive.Portal>
  </Primitive.Root>;
}
