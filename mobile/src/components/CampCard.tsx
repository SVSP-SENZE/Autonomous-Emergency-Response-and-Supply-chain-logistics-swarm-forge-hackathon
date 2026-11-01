import React from 'react';
import { View, Text, StyleSheet } from 'react-native';
import type { ReliefCentre } from '../types';

interface Props {
  centre: ReliefCentre;
}

const PRIORITY_COLOR: Record<string, string> = {
  critical: '#f15b5b',
  high: '#ff963d',
  medium: '#ffd740',
  low: '#21b989',
};

const STATUS_LABEL: Record<string, string> = {
  operational: '✅ Operational',
  degraded: '⚠️ Degraded',
  unavailable: '❌ Unavailable',
};

export function CampCard({ centre }: Props) {
  const dot = PRIORITY_COLOR[centre.priority] ?? '#a7b9cc';
  return (
    <View style={styles.card}>
      <View style={styles.header}>
        <View style={[styles.dot, { backgroundColor: dot }]} />
        <Text style={styles.name}>{centre.name}</Text>
      </View>
      <Text style={styles.district}>{centre.district}</Text>
      <View style={styles.row}>
        <Text style={styles.chip}>{STATUS_LABEL[centre.operational_status] ?? centre.operational_status}</Text>
        {centre.water_shortage && (
          <Text style={[styles.chip, styles.warning]}>💧 Water shortage</Text>
        )}
      </View>
      <Text style={styles.pop}>
        👥 {centre.affected_population.toLocaleString()} people
      </Text>
      <Text style={styles.coords}>
        {centre.latitude.toFixed(4)}, {centre.longitude.toFixed(4)}
      </Text>
    </View>
  );
}

const styles = StyleSheet.create({
  card: {
    backgroundColor: '#10243a',
    borderRadius: 10,
    padding: 14,
    marginBottom: 10,
    borderWidth: 1,
    borderColor: '#20364d',
    gap: 6,
  },
  header: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 8,
  },
  dot: {
    width: 10,
    height: 10,
    borderRadius: 5,
  },
  name: {
    color: '#f1f5f9',
    fontWeight: '700',
    fontSize: 15,
    flex: 1,
  },
  district: {
    color: '#a7b9cc',
    fontSize: 13,
    marginLeft: 18,
  },
  row: {
    flexDirection: 'row',
    gap: 8,
    flexWrap: 'wrap',
  },
  chip: {
    color: '#21b989',
    fontSize: 12,
    fontWeight: '600',
    backgroundColor: 'rgba(33,185,137,0.12)',
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },
  warning: {
    color: '#ffd740',
    backgroundColor: 'rgba(255,215,64,0.12)',
  },
  pop: {
    color: '#a7b9cc',
    fontSize: 13,
  },
  coords: {
    color: '#6c8099',
    fontSize: 11,
    fontFamily: 'monospace',
  },
});
