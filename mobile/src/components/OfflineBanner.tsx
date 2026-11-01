import React from 'react';
import { View, Text, StyleSheet } from 'react-native';

interface Props {
  offline: boolean;
}

export function OfflineBanner({ offline }: Props) {
  if (!offline) return null;
  return (
    <View style={styles.banner}>
      <Text style={styles.icon}>📡</Text>
      <Text style={styles.text}>No internet — showing cached data · SMS fallback active</Text>
    </View>
  );
}

const styles = StyleSheet.create({
  banner: {
    flexDirection: 'row',
    alignItems: 'center',
    backgroundColor: '#7d3f00',
    paddingHorizontal: 12,
    paddingVertical: 6,
    gap: 8,
  },
  icon: {
    fontSize: 14,
  },
  text: {
    color: '#ffd580',
    fontSize: 12,
    fontWeight: '600',
    flex: 1,
  },
});
