import React, { useState } from 'react';
import {
  View,
  Text,
  StyleSheet,
  ScrollView,
  TouchableOpacity,
  TextInput,
  Alert,
  ActivityIndicator,
  Switch,
} from 'react-native';
import * as Location from 'expo-location';
import { reportHazard } from '../../api/hazards';
import { createIncident } from '../../api/incidents';
import type { SimulationEventType } from '../../types';

interface HazardForm {
  eventType: SimulationEventType;
  description: string;
  blockageReason: string;
  useCurrentLocation: boolean;
  manualLat: string;
  manualLng: string;
  locationName: string;
}

const EVENT_TYPES: { value: SimulationEventType; label: string; emoji: string }[] = [
  { value: 'road_blocked', label: 'Road Blocked', emoji: '🚧' },
  { value: 'bridge_collapse', label: 'Bridge Collapse', emoji: '🌉' },
  { value: 'new_flood_report', label: 'New Flood Area', emoji: '🌊' },
  { value: 'rainfall_escalation', label: 'Rainfall Escalation', emoji: '🌧️' },
  { value: 'vehicle_breakdown', label: 'Vehicle Breakdown', emoji: '🚗' },
];

export default function ReportHazardScreen() {
  const [form, setForm] = useState<HazardForm>({
    eventType: 'road_blocked',
    description: '',
    blockageReason: '',
    useCurrentLocation: true,
    manualLat: '',
    manualLng: '',
    locationName: '',
  });
  const [loading, setLoading] = useState(false);
  const [gpsLoading, setGpsLoading] = useState(false);
  const [capturedLocation, setCapturedLocation] = useState<{ lat: number; lng: number } | null>(null);

  const captureGps = async () => {
    setGpsLoading(true);
    try {
      const { status } = await Location.requestForegroundPermissionsAsync();
      if (status !== 'granted') {
        Alert.alert('Permission denied', 'Cannot capture GPS location. Enter manually instead.');
        return;
      }
      const loc = await Location.getCurrentPositionAsync({ accuracy: Location.Accuracy.High });
      setCapturedLocation({ lat: loc.coords.latitude, lng: loc.coords.longitude });
      Alert.alert('📍 Location captured', `${loc.coords.latitude.toFixed(5)}, ${loc.coords.longitude.toFixed(5)}`);
    } catch {
      Alert.alert('GPS Error', 'Could not get location. Enter coordinates manually.');
    } finally {
      setGpsLoading(false);
    }
  };

  const handleSubmit = async () => {
    if (!form.description.trim()) {
      Alert.alert('Required', 'Please add a description of the hazard.');
      return;
    }

    let lat: number | undefined;
    let lng: number | undefined;

    if (form.useCurrentLocation && capturedLocation) {
      lat = capturedLocation.lat;
      lng = capturedLocation.lng;
    } else if (!form.useCurrentLocation) {
      lat = parseFloat(form.manualLat);
      lng = parseFloat(form.manualLng);
      if (isNaN(lat) || isNaN(lng)) {
        Alert.alert('Invalid coordinates', 'Please enter valid latitude and longitude.');
        return;
      }
    }

    Alert.alert(
      'Submit Hazard Report?',
      `Type: ${form.eventType.replace(/_/g, ' ')}\n${lat !== undefined ? `Location: ${lat?.toFixed(4)}, ${lng?.toFixed(4)}` : 'No GPS location'}`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Submit',
          onPress: async () => {
            setLoading(true);
            try {
              // 1. Register in the live incident registry (instant alert on Command Centre map & table)
              const incidentType =
                form.eventType === 'road_blocked' || form.eventType === 'bridge_collapse'
                  ? 'infrastructure_damage'
                  : 'flood';

              await createIncident({
                incident_type: incidentType,
                title: `Field Report: ${form.eventType.replace(/_/g, ' ').toUpperCase()}`,
                description: `${form.description}${form.blockageReason ? ` | Reason: ${form.blockageReason}` : ''}`,
                source: 'operator',
                severity: 'high',
                status: 'reported',
                location_name: form.locationName || (lat ? `GPS ${lat.toFixed(4)}, ${lng!.toFixed(4)}` : 'Field Location'),
                latitude: lat ?? 10.787,
                longitude: lng ?? 79.1378,
                affected_population: 0,
              });

              // 2. Also register simulation event with road segment target if road blocked
              try {
                await reportHazard({
                  event_type: form.eventType,
                  title: `Field Report: ${form.eventType.replace(/_/g, ' ')}`,
                  description: form.description,
                  severity: 'high',
                  road_segment_id: 1,
                  blockage_reason: form.blockageReason || undefined,
                });
              } catch {
                // Secondary simulation event optional
              }

              Alert.alert(
                '✅ Reported',
                'Hazard submitted to ReliefMesh Command Centre. Responders and live maps have been alerted.',
              );
              setForm({
                eventType: 'road_blocked',
                description: '',
                blockageReason: '',
                useCurrentLocation: true,
                manualLat: '',
                manualLng: '',
                locationName: '',
              });
              setCapturedLocation(null);
            } catch (err: any) {
              Alert.alert('Submission failed', err?.message ?? 'Could not submit hazard report.');
            } finally {
              setLoading(false);
            }
          },
        },
      ],
    );
  };

  return (
    <ScrollView style={styles.root} contentContainerStyle={styles.scroll} keyboardShouldPersistTaps="handled">
      <Text style={styles.heading}>⚠️ Report Field Hazard</Text>
      <Text style={styles.sub}>Report blocked roads or hazards to update the command centre routing.</Text>

      {/* Event type */}
      <Text style={styles.label}>Hazard Type</Text>
      <View style={styles.typeGrid}>
        {EVENT_TYPES.map(t => (
          <TouchableOpacity
            key={t.value}
            style={[styles.typeChip, form.eventType === t.value && styles.typeChipActive]}
            onPress={() => setForm(f => ({ ...f, eventType: t.value }))}
          >
            <Text style={styles.typeEmoji}>{t.emoji}</Text>
            <Text style={[styles.typeLabel, form.eventType === t.value && styles.typeLabelActive]}>
              {t.label}
            </Text>
          </TouchableOpacity>
        ))}
      </View>

      {/* Description */}
      <Text style={styles.label}>Description *</Text>
      <TextInput
        style={[styles.input, styles.multiline]}
        placeholder="Describe the hazard clearly…"
        placeholderTextColor="#4a6a80"
        value={form.description}
        onChangeText={v => setForm(f => ({ ...f, description: v }))}
        multiline
        numberOfLines={4}
        textAlignVertical="top"
      />

      {/* Blockage reason (for road blocked) */}
      {(form.eventType === 'road_blocked' || form.eventType === 'bridge_collapse') && (
        <>
          <Text style={styles.label}>Blockage reason (optional)</Text>
          <TextInput
            style={styles.input}
            placeholder="e.g. Ayyampettai causeway submerged"
            placeholderTextColor="#4a6a80"
            value={form.blockageReason}
            onChangeText={v => setForm(f => ({ ...f, blockageReason: v }))}
          />
        </>
      )}

      {/* Landmark */}
      <Text style={styles.label}>Nearest landmark (optional)</Text>
      <TextInput
        style={styles.input}
        placeholder="e.g. Near Thanjavur NH-67 bridge"
        placeholderTextColor="#4a6a80"
        value={form.locationName}
        onChangeText={v => setForm(f => ({ ...f, locationName: v }))}
      />

      {/* Location */}
      <View style={styles.toggleRow}>
        <Text style={styles.label}>Use current GPS location</Text>
        <Switch
          value={form.useCurrentLocation}
          onValueChange={v => setForm(f => ({ ...f, useCurrentLocation: v }))}
          trackColor={{ true: '#319aff', false: '#20364d' }}
          thumbColor="#f1f5f9"
        />
      </View>

      {form.useCurrentLocation ? (
        <TouchableOpacity style={styles.gpsBtn} onPress={captureGps} disabled={gpsLoading}>
          {gpsLoading ? (
            <ActivityIndicator size="small" color="#319aff" />
          ) : (
            <Text style={styles.gpsBtnText}>
              {capturedLocation
                ? `📍 ${capturedLocation.lat.toFixed(4)}, ${capturedLocation.lng.toFixed(4)} (tap to refresh)`
                : '📍 Capture GPS Location'}
            </Text>
          )}
        </TouchableOpacity>
      ) : (
        <View style={styles.coordRow}>
          <TextInput
            style={[styles.input, styles.coordInput]}
            placeholder="Latitude"
            placeholderTextColor="#4a6a80"
            value={form.manualLat}
            onChangeText={v => setForm(f => ({ ...f, manualLat: v }))}
            keyboardType="numeric"
          />
          <TextInput
            style={[styles.input, styles.coordInput]}
            placeholder="Longitude"
            placeholderTextColor="#4a6a80"
            value={form.manualLng}
            onChangeText={v => setForm(f => ({ ...f, manualLng: v }))}
            keyboardType="numeric"
          />
        </View>
      )}

      {/* Submit */}
      <TouchableOpacity style={styles.submitBtn} onPress={handleSubmit} disabled={loading}>
        {loading ? (
          <ActivityIndicator size="small" color="#fff" />
        ) : (
          <Text style={styles.submitBtnText}>🚨 Submit Hazard Report</Text>
        )}
      </TouchableOpacity>
    </ScrollView>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#071321' },
  scroll: { padding: 20, paddingBottom: 60 },
  heading: { color: '#f1f5f9', fontSize: 24, fontWeight: '800', marginBottom: 6 },
  sub: { color: '#a7b9cc', fontSize: 14, marginBottom: 24, lineHeight: 20 },
  label: { color: '#a7b9cc', fontSize: 13, fontWeight: '600', textTransform: 'uppercase', letterSpacing: 0.8, marginBottom: 10, marginTop: 16 },
  typeGrid: { flexDirection: 'row', flexWrap: 'wrap', gap: 8 },
  typeChip: {
    flexDirection: 'row',
    alignItems: 'center',
    gap: 6,
    backgroundColor: '#10243a',
    borderRadius: 8,
    paddingHorizontal: 12,
    paddingVertical: 10,
    borderWidth: 1,
    borderColor: '#20364d',
  },
  typeChipActive: { backgroundColor: '#1a3a5c', borderColor: '#319aff' },
  typeEmoji: { fontSize: 18 },
  typeLabel: { color: '#6c8099', fontSize: 13, fontWeight: '600' },
  typeLabelActive: { color: '#319aff' },
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
  multiline: { minHeight: 100, paddingTop: 12 },
  toggleRow: { flexDirection: 'row', justifyContent: 'space-between', alignItems: 'center', marginTop: 16 },
  gpsBtn: {
    backgroundColor: '#0d2035',
    borderRadius: 8,
    padding: 14,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#319aff',
    marginTop: 10,
  },
  gpsBtnText: { color: '#319aff', fontWeight: '600', fontSize: 14 },
  coordRow: { flexDirection: 'row', gap: 10, marginTop: 10 },
  coordInput: { flex: 1 },
  submitBtn: {
    backgroundColor: '#c0392b',
    borderRadius: 10,
    paddingVertical: 16,
    alignItems: 'center',
    marginTop: 28,
    borderWidth: 1,
    borderColor: '#f15b5b',
  },
  submitBtnText: { color: '#fff', fontWeight: '800', fontSize: 16 },
});
