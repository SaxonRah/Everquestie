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
  // Combat-ability identities come from the client db-string system and are NOT
  // spell IDs. Upstream itself correlates them to spell mechanics by exact name.
  // getLocalSpellByName has a fuzzy fallback, so resolveCombatAbility verifies the
  // returned spell name before accepting the enrichment.
  combatAbilities: {
    getter: 'getLocalSpellByName',
    kind: 'combat_ability',
    resolver: 'combat_ability_exact_name',
  },
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

function exactName(value) {
  return String(value ?? '').trim().toLowerCase();
}

async function resolveRecord(local, spec, externalId, name) {
  const getter = local[spec.getter];
  if (typeof getter !== 'function') {
    return { missingGetter: true };
  }

  if (spec.resolver === 'combat_ability_exact_name') {
    const spell = await getter(name);
    if (spell === null || spell === undefined) return { record: null, reason: 'not_found' };
    const spellName = spell && typeof spell === 'object' ? spell.name : '';
    if (!spellName || exactName(spellName) !== exactName(name)) {
      return { record: null, reason: 'non_exact_spell_name_match_rejected' };
    }
    const spellId = spell && typeof spell === 'object' ? spell.id : null;
    return {
      record: {
        ...spell,
        // Preserve the combat-ability namespace as the record identity. The spell
        // ID remains explicit enrichment evidence rather than replacing that ID.
        id: String(externalId),
        abilityId: String(externalId),
        name,
        spellId: spellId === null || spellId === undefined ? null : String(spellId),
        spellName,
        identityJoin: {
          method: 'exact_case_insensitive_name',
          combatAbilityId: String(externalId),
          combatAbilityName: name,
          matchedSpellId: spellId === null || spellId === undefined ? null : String(spellId),
          matchedSpellName: spellName,
        },
      },
    };
  }

  const record = await getter(String(externalId));
  return { record, reason: record === null || record === undefined ? 'not_found' : null };
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

    if (typeof local[spec.getter] !== 'function') {
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
        const resolved = await resolveRecord(local, spec, String(externalId), name);
        if (resolved.missingGetter) {
          errors += 1;
          emit({
            type: 'record_error',
            system,
            kind: spec.kind,
            external_id: String(externalId),
            name,
            reason: 'getter_missing',
          });
          continue;
        }
        const record = resolved.record;
        if (record === null || record === undefined) {
          errors += 1;
          emit({
            type: 'record_error',
            system,
            kind: spec.kind,
            external_id: String(externalId),
            name,
            reason: resolved.reason || 'not_found',
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
