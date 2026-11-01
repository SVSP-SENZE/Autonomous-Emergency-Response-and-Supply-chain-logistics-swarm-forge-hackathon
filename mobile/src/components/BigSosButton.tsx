import React from 'react';
import { TouchableOpacity, Text, StyleSheet, View, ActivityIndicator } from 'react-native';

interface Props {
  onPress: () => void;
  loading?: boolean;
  disabled?: boolean;
}

export function BigSosButton({ onPress, loading = false, disabled = false }: Props) {
  return (
    <TouchableOpacity
      onPress={onPress}
      disabled={disabled || loading}
      style={[styles.button, (disabled || loading) && styles.disabled]}
      activeOpacity={0.75}
      accessibilityLabel="Send Emergency SOS"
      accessibilityRole="button"
    >
      <View style={styles.inner}>
        {loading ? (
          <ActivityIndicator size="large" color="#fff" />
        ) : (
          <>
            <Text style={styles.icon}>🆘</Text>
            <Text style={styles.label}>SOS</Text>
            <Text style={styles.sub}>Tap to send emergency beacon</Text>
          </>
        )}
      </View>
    </TouchableOpacity>
  );
}

const styles = StyleSheet.create({
  button: {
    width: 220,
    height: 220,
    borderRadius: 110,
    backgroundColor: '#c0392b',
    alignItems: 'center',
    justifyContent: 'center',
    shadowColor: '#f15b5b',
    shadowOpacity: 0.7,
    shadowRadius: 28,
    shadowOffset: { width: 0, height: 0 },
    elevation: 20,
    borderWidth: 4,
    borderColor: '#ff6b6b',
  },
  disabled: {
    backgroundColor: '#5a1a1a',
    shadowOpacity: 0.2,
    borderColor: '#7a3a3a',
  },
  inner: {
    alignItems: 'center',
    gap: 4,
  },
  icon: {
    fontSize: 48,
  },
  label: {
    fontSize: 42,
    fontWeight: '900',
    color: '#fff',
    letterSpacing: 6,
  },
  sub: {
    fontSize: 12,
    color: 'rgba(255,255,255,0.75)',
    textAlign: 'center',
    marginTop: 4,
  },
});
