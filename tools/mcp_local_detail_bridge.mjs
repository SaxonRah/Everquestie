#!/usr/bin/env node

import fs from 'node:fs/promises';
import path from 'node:path';
import { pathToFileURL } from 'node:url';

// Keep this bridge deliberately small. everquest1-mcp already owns the parsers;
// EverQuestie only asks its compiled local-data module for the structured record
// behind each identity captured by save_data_snapshot.
const GETTERS = {
  spells: { getter: 'getLocalSpell', kind: 'spell' },
  zones: { getter: 'getLocalZone', kind: 'zone' },
  factions: { getter: 'getFaction', kind: 'faction' },
  achievements: { getter: 'getAchievement', kind: 'achievement' },
  aaAbilities: { getter: 'getAAAbility', kind: 'aa' },
  overseerMinions: { getter: 'getOverseerMinion', kind: 'overseer_agent' },
  overseerQuests: { getter: 'getOverseerQuest', kind: 'overseer_quest' },
  mercenaries: { getter: 'getMercenary', kind: 'mercenary' },
  tributes: { getter: 'getTribute', kind: 'tribute' },
  lore: { getter: 'getLore', kind: 'lore' },
  // EQ combat abilities are spell records flagged/used as disciplines. The
  // snapshot IDs therefore resolve through the same authoritative spell parser.
  combatAbilities: { getter: 'getLocalSpell', kind: 'combat_ability' },
};

function emit(message) {
  process.stdout.write(`${JSON.stringify(message)}\n`);
}

async function readSnapshot(source) {
  if (source === '-') {
    let input = '';
    process.stdin.setEncoding('utf8');
    for await (const chunk of process.stdin) input += chunk;
    return JSON.parse(input);
  }
  return JSON.parse(await fs.readFile(source, 'utf8'));
}

async function main() {
  const [mcpRootArg, snapshotSource = '-'] = process.argv.slice(2);
  if (!mcpRootArg) {
    throw new Error('Usage: mcp_local_detail_bridge.mjs <everquest1-mcp-root> [snapshot-json|-]');
  }

  const mcpRoot = path.resolve(mcpRootArg);
  const snapshot = await readSnapshot(snapshotSource);
  if (!snapshot || typeof snapshot !== 'object' || !snapshot.systems || typeof snapshot.systems !== 'object') {
    throw new Error('Snapshot does not contain a systems object.');
  }

  if (snapshot.eqPath && !process.env.EQ_GAME_PATH) {
    process.env.EQ_GAME_PATH = String(snapshot.eqPath);
  }

  const modulePath = path.join(mcpRoot, 'dist', 'sources', 'index.js');
  const local = await import(pathToFileURL(modulePath).href);

  for (const [system, spec] of Object.entries(GETTERS)) {
    const payload = snapshot.systems[system];
    const names = payload && typeof payload === 'object' ? payload.names : null;
    if (!names || typeof names !== 'object' || Array.isArray(names)) continue;

    const getter = local[spec.getter];
    if (typeof getter !== 'function') {
      emit({ type: 'system_missing', system, kind: spec.kind, getter: spec.getter });
      continue;
    }

    const entries = Object.entries(names).filter(([, value]) => String(value ?? '').trim());
    emit({ type: 'system_start', system, kind: spec.kind, getter: spec.getter, total: entries.length });

    let imported = 0;
    let errors = 0;
    for (const [externalId, rawName] of entries) {
      const name = String(rawName ?? '').trim();
      try {
        const record = await getter(String(externalId));
        if (record === null || record === undefined) {
          errors += 1;
          emit({
            type: 'record_error',
            system,
            kind: spec.kind,
            external_id: String(externalId),
            name,
            reason: 'not_found',
          });
          continue;
        }
        imported += 1;
        emit({
          type: 'record',
          system,
          kind: spec.kind,
          external_id: String(externalId),
          name,
          getter: spec.getter,
          record,
        });
      } catch (error) {
        errors += 1;
        emit({
          type: 'record_error',
          system,
          kind: spec.kind,
          external_id: String(externalId),
          name,
          reason: error instanceof Error ? error.message : String(error),
        });
      }
    }

    emit({ type: 'system_done', system, kind: spec.kind, imported, errors, total: entries.length });
  }
}

main().catch((error) => {
  process.stderr.write(`${error instanceof Error ? error.stack || error.message : String(error)}\n`);
  process.exitCode = 1;
});
