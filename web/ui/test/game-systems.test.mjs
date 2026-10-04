import test from 'node:test';
import assert from 'node:assert/strict';
import {GAME_SYSTEMS,isKnownGameSystem} from '../src/game-systems.mjs';
test('system suggestions preserve distinct rules editions without closing custom values',()=>{
 assert.equal(new Set(GAME_SYSTEMS).size,GAME_SYSTEMS.length);
 for(const system of GAME_SYSTEMS)assert.ok(system.trim()===system&&system.length<=120);
 assert.ok(isKnownGameSystem('Dungeons & Dragons — 5e (2014)'));
 assert.ok(isKnownGameSystem('Dungeons & Dragons — 5.5e (2024)'));
 assert.ok(isKnownGameSystem('Pathfinder — 2e Remaster'));
 assert.equal(isKnownGameSystem('A fictional custom system'),false);
});
