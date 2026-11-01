import React, { useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  Alert,
  TextInput,
  Switch,
} from 'react-native';
import * as Location from 'expo-location';
import * as SMS from 'expo-sms';
import { BigSosButton } from '../../components/BigSosButton';
import { OfflineBanner } from '../../components/OfflineBanner';
import { createIncident } from '../../api/incidents';
import type { SosForm } from '../../types';

const EMERGENCY_NUMBER = process.env.EXPO_PUBLIC_EMERGENCY_SMS_NUMBER ?? '+911234567890';

const WATER_LEVELS = ['ankle', 'knee', 'waist', 'chest', 'roof'] as const;

const WATER_LABELS: Record<string, string> = {
  ankle: '🌊 Ankle deep',
  knee: '🌊 Knee deep',
  waist: '🌊 Waist deep',
  chest: '🌊 Chest deep',
  roof: '🌊 Rooftop level',
};

export default function SosScreen() {
  const [loading, setLoading] = useState(false);
  const [sent, setSent] = useState(false);
  const [offline, setOffline] = useState(false);
  const [form, setForm] = useState<SosForm>({
    peopleCount: 1,
    hasMedical: false,
    hasElderly: false,
    hasChildren: false,
    waterLevel: 'knee',
    locationName: '',
  });

  const buildDescription = (f: SosForm, lat: number, lng: number) => {
    const flags = [
      f.hasMedical && 'MEDICAL EMERGENCY',
      f.hasElderly && 'elderly persons',
      f.hasChildren && 'children',
    ].filter(Boolean).join(', ');

    return [
      `CITIZEN SOS — ${f.peopleCount} person(s) trapped.`,
      flags && `Critical flags: ${flags}.`,
      `Water level: ${f.waterLevel}.`,
      f.locationName && `Near: ${f.locationName}.`,
      `GPS: ${lat.toFixed(5)}, ${lng.toFixed(5)}.`,
    ].filter(Boolean).join(' ');
  };

  const sendSosSms = async (description: string) => {
    const available = await SMS.isAvailableAsync();
    if (!available) {
      Alert.alert(
        'SMS not available',
        `Please call emergency services manually.\nYour location info: ${description}`,
      );
      return;
    }
    await SMS.sendSMSAsync([EMERGENCY_NUMBER], `🆘 RELIEFMESH SOS\n${description}`);
  };

  const handleSos = useCallback(async () => {
    setLoading(true);
    setOffline(false);

    // 1. Request location permission
    const { status } = await Location.requestForegroundPermissionsAsync();
    if (status !== 'granted') {
      Alert.alert(
        'Location required',
        'Please allow location access so rescuers can find you. Your SOS will still be sent via SMS.',
      );
      await sendSosSms('Location unavailable — GPS denied.');
      setLoading(false);
      return;
    }

    // 2. Get GPS
    let lat = 0;
    let lng = 0;
    try {
      const loc = await Location.getCurrentPositionAsync({
        accuracy: Location.Accuracy.High,
      });
      lat = loc.coords.latitude;
      lng = loc.coords.longitude;
    } catch {
      await sendSosSms('Location fetch failed — GPS error.');
      setLoading(false);
      return;
    }

    const description = buildDescription(form, lat, lng);

    // 3. Try backend API
    try {
      await createIncident({
        incident_type: 'flood',
        title: `Citizen SOS — ${form.peopleCount} person(s) trapped`,
        description,
        source: 'citizen_report',
        severity: 'critical',
        status: 'reported',
        location_name: form.locationName || `GPS ${lat.toFixed(4)}, ${lng.toFixed(4)}`,
        latitude: lat,
        longitude: lng,
        affected_population: form.peopleCount,
      });
      setSent(true);
      Alert.alert(
        '✅ SOS Sent!',
        'Your emergency beacon has been received by the ReliefMesh Command Centre. Help is being dispatched.',
        [{ text: 'OK' }],
      );
    } catch {
      // 4. Fallback: SMS
      setOffline(true);
      Alert.alert(
        '⚠️ Server unreachable',
        'Sending emergency SMS instead. Keep your phone charged and wait for rescue.',
        [
          {
            text: 'Send SMS now',
            onPress: () => sendSosSms(description),
          },
          { text: 'Cancel', style: 'cancel' },
        ],
      );
    } finally {
      setLoading(false);
    }
  }, [form]);

  if (sent) {
    return (
      <View style={styles.sentContainer}>
        <Text style={styles.sentIcon}>✅</Text>
        <Text style={styles.sentTitle}>SOS Received!</Text>
        <Text style={styles.sentSub}>
          The ReliefMesh Command Centre has your location. Stay visible and keep your phone charged.
        </Text>
        <TouchableOpacity style={styles.resetBtn} onPress={() => setSent(false)}>
          <Text style={styles.resetBtnText}>Send another SOS</Text>
        </TouchableOpacity>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <OfflineBanner offline={offline} />
      <ScrollView contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
        {/* Header */}
        <Text style={styles.heading}>🆘 Emergency SOS</Text>
        <Text style={styles.sub}>Fill in details below, then press the button to alert rescuers.</Text>

        {/* People count */}
        <View style={styles.section}>
          <Text style={styles.label}>People trapped</Text>
          <View style={styles.counter}>
            <TouchableOpacity
              style={styles.counterBtn}
              onPress={() => setForm(f => ({ ...f, peopleCount: Math.max(1, f.peopleCount - 1) }))}
            >
              <Text style={styles.counterBtnText}>−</Text>
            </TouchableOpacity>
            <Text style={styles.counterValue}>{form.peopleCount}</Text>
            <TouchableOpacity
              style={styles.counterBtn}
              onPress={() => setForm(f => ({ ...f, peopleCount: f.peopleCount + 1 }))}
            >
              <Text style={styles.counterBtnText}>+</Text>
            </TouchableOpacity>
          </View>
        </View>

        {/* Critical flags */}
        <View style={styles.section}>
          <Text style={styles.label}>Critical flags</Text>
          <View style={styles.toggleRow}>
            <Text style={styles.toggleLabel}>🏥 Medical emergency</Text>
            <Switch
              value={form.hasMedical}
              onValueChange={v => setForm(f => ({ ...f, hasMedical: v }))}
              trackColor={{ true: '#f15b5b', false: '#20364d' }}
              thumbColor="#f1f5f9"
            />
          </View>
          <View style={styles.toggleRow}>
            <Text style={styles.toggleLabel}>👴 Elderly persons</Text>
            <Switch
              value={form.hasElderly}
              onValueChange={v => setForm(f => ({ ...f, hasElderly: v }))}
              trackColor={{ true: '#ff963d', false: '#20364d' }}
              thumbColor="#f1f5f9"
            />
          </View>
          <View style={styles.toggleRow}>
            <Text style={styles.toggleLabel}>👶 Children present</Text>
            <Switch
              value={form.hasChildren}
              onValueChange={v => setForm(f => ({ ...f, hasChildren: v }))}
              trackColor={{ true: '#ffd740', false: '#20364d' }}
              thumbColor="#f1f5f9"
            />
          </View>
        </View>

        {/* Water level */}
        <View style={styles.section}>
          <Text style={styles.label}>Water level</Text>
          <View style={styles.waterRow}>
            {WATER_LEVELS.map(level => (
              <TouchableOpacity
                key={level}
                style={[styles.waterChip, form.waterLevel === level && styles.waterChipActive]}
                onPress={() => setForm(f => ({ ...f, waterLevel: level }))}
              >
                <Text
                  style={[styles.waterChipText, form.waterLevel === level && styles.waterChipTextActive]}
                >
                  {WATER_LABELS[level]}
                </Text>
              </TouchableOpacity>
            ))}
          </View>
        </View>

        {/* Location name */}
        <View style={styles.section}>
          <Text style={styles.label}>Nearest landmark (optional)</Text>
          <TextInput
            style={styles.input}
            placeholder="e.g. near Thanjavur bus stand"
            placeholderTextColor="#4a6a80"
            value={form.locationName}
            onChangeText={v => setForm(f => ({ ...f, locationName: v }))}
          />
        </View>

        {/* Big SOS button */}
        <View style={styles.buttonContainer}>
          <BigSosButton onPress={handleSos} loading={loading} />
        </View>

        <Text style={styles.note}>
          📍 GPS location will be captured automatically when you press SOS.{'\n'}
          📶 If offline, an emergency SMS will be sent instead.
        </Text>
      </ScrollView>
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#071321' },
  scroll: { padding: 20, paddingBottom: 40 },
  heading: {
    color: '#f1f5f9',
    fontSize: 26,
    fontWeight: '800',
    marginBottom: 6,
  },
  sub: {
    color: '#a7b9cc',
    fontSize: 14,
    marginBottom: 24,
    lineHeight: 20,
  },
  section: {
    marginBottom: 22,
  },
  label: {
    color: '#a7b9cc',
    fontSize: 13,
    fontWeight: '600',
    textTransform: 'uppercase',
    letterSpacing: 0.8,
    marginBottom: 10,
  },
  counter: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 20,
  },
  counterBtn: {
    width: 48,
    height: 48,
    borderRadius: 24,
    backgroundColor: '#10243a',
    borderWidth: 1,
    borderColor: '#20364d',
    alignItems: 'center',
    justifyContent: 'center',
  },
  counterBtnText: {
    color: '#f1f5f9',
    fontSize: 24,
    fontWeight: '700',
  },
  counterValue: {
    color: '#f1f5f9',
    fontSize: 36,
    fontWeight: '800',
    minWidth: 50,
    textAlign: 'center',
  },
  toggleRow: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
    paddingVertical: 10,
    borderBottomWidth: 1,
    borderBottomColor: '#10243a',
  },
  toggleLabel: {
    color: '#f1f5f9',
    fontSize: 15,
  },
  waterRow: {
    flexDirection: 'row',
    flexWrap: 'wrap',
    gap: 8,
  },
  waterChip: {
    backgroundColor: '#10243a',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 8,
    borderWidth: 1,
    borderColor: '#20364d',
  },
  waterChipActive: {
    backgroundColor: '#1a3a5c',
    borderColor: '#319aff',
  },
  waterChipText: {
    color: '#6c8099',
    fontSize: 13,
  },
  waterChipTextActive: {
    color: '#319aff',
    fontWeight: '700',
  },
  input: {
    backgroundColor: '#10243a',
    borderRadius: 8,
    borderWidth: 1,
    borderColor: '#20364d',
    color: '#f1f5f9',
    paddingHorizontal: 14,
    paddingVertical: 12,
    fontSize: 15,
  },
  buttonContainer: {
    alignItems: 'center',
    marginVertical: 32,
  },
  note: {
    color: '#4a6a80',
    fontSize: 12,
    textAlign: 'center',
    lineHeight: 18,
  },
  // Sent state
  sentContainer: {
    flex: 1,
    backgroundColor: '#071321',
    alignItems: 'center',
    justifyContent: 'center',
    padding: 32,
    gap: 16,
  },
  sentIcon: { fontSize: 64 },
  sentTitle: {
    color: '#21b989',
    fontSize: 32,
    fontWeight: '800',
  },
  sentSub: {
    color: '#a7b9cc',
    fontSize: 15,
    textAlign: 'center',
    lineHeight: 22,
  },
  resetBtn: {
    marginTop: 20,
    backgroundColor: '#10243a',
    borderRadius: 8,
    paddingHorizontal: 24,
    paddingVertical: 12,
    borderWidth: 1,
    borderColor: '#20364d',
  },
  resetBtnText: { color: '#a7b9cc', fontSize: 14 },
});
