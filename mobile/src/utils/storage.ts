import AsyncStorage from '@react-native-async-storage/async-storage';
import type { ReliefCentre } from '../types';

const KEYS = {
  CAMPS: 'reliefmesh:camps',
  ROLE: 'reliefmesh:role',
} as const;

/** Persist relief centres for offline access. */
export async function saveCamps(centres: ReliefCentre[]): Promise<void> {
  try {
    await AsyncStorage.setItem(KEYS.CAMPS, JSON.stringify(centres));
  } catch {
    // storage failure is non-fatal
  }
}

/** Load cached relief centres. Returns empty array on miss or error. */
export async function loadCamps(): Promise<ReliefCentre[]> {
  try {
    const raw = await AsyncStorage.getItem(KEYS.CAMPS);
    if (!raw) return [];
    return JSON.parse(raw) as ReliefCentre[];
  } catch {
    return [];
  }
}

/** Persist the user's chosen role ('citizen' | 'volunteer'). */
export async function saveRole(role: string): Promise<void> {
  try {
    await AsyncStorage.setItem(KEYS.ROLE, role);
  } catch {
    // non-fatal
  }
}

/** Load the persisted role. Returns null if not set. */
export async function loadRole(): Promise<string | null> {
  try {
    return await AsyncStorage.getItem(KEYS.ROLE);
  } catch {
    return null;
  }
}
