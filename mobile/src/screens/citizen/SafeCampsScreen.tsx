import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  RefreshControl,
  Platform,
} from 'react-native';
import MapView, { Marker, PROVIDER_GOOGLE } from 'react-native-maps';
import { CampCard } from '../../components/CampCard';
import { OfflineBanner } from '../../components/OfflineBanner';
import { listReliefCentres } from '../../api/relief_centres';
import { saveCamps, loadCamps } from '../../utils/storage';
import type { ReliefCentre } from '../../types';

const MAPS_API_KEY = process.env.EXPO_PUBLIC_GOOGLE_MAPS_API_KEY ?? '';

// Centre of Tamil Nadu flood zone
const DEFAULT_REGION = {
  latitude: 10.787,
  longitude: 79.137,
  latitudeDelta: 1.5,
  longitudeDelta: 1.5,
};

const PRIORITY_COLOR: Record<string, string> = {
  critical: '#f15b5b',
  high: '#ff963d',
  medium: '#ffd740',
  low: '#21b989',
};

export default function SafeCampsScreen() {
  const [centres, setCentres] = useState<ReliefCentre[]>([]);
  const [loading, setLoading] = useState(true);
  const [offline, setOffline] = useState(false);
  const [view, setView] = useState<'list' | 'map'>('list');
  const [refreshing, setRefreshing] = useState(false);

  const fetchCentres = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    try {
      const res = await listReliefCentres();
      setCentres(res.items);
      setOffline(false);
      await saveCamps(res.items);
    } catch {
      setOffline(true);
      const cached = await loadCamps();
      if (cached.length > 0) setCentres(cached);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => {
    // Load cache immediately for instant display, then try network
    loadCamps().then(cached => {
      if (cached.length > 0) {
        setCentres(cached);
        setLoading(false);
      }
    });
    fetchCentres();
  }, [fetchCentres]);

  return (
    <View style={styles.root}>
      <OfflineBanner offline={offline} />

      {/* Toggle */}
      <View style={styles.toggle}>
        <TouchableOpacity
          style={[styles.toggleBtn, view === 'list' && styles.toggleActive]}
          onPress={() => setView('list')}
        >
          <Text style={[styles.toggleText, view === 'list' && styles.toggleTextActive]}>
            📋 List
          </Text>
        </TouchableOpacity>
        <TouchableOpacity
          style={[styles.toggleBtn, view === 'map' && styles.toggleActive]}
          onPress={() => setView('map')}
        >
          <Text style={[styles.toggleText, view === 'map' && styles.toggleTextActive]}>
            🗺️ Map
          </Text>
        </TouchableOpacity>
      </View>

      {offline && centres.length > 0 && (
        <Text style={styles.cacheNote}>Showing cached data from last sync</Text>
      )}

      {view === 'list' ? (
        <FlatList
          data={centres}
          keyExtractor={c => String(c.id)}
          contentContainerStyle={styles.list}
          renderItem={({ item }) => <CampCard centre={item} />}
          refreshControl={
            <RefreshControl
              refreshing={refreshing}
              onRefresh={() => fetchCentres(true)}
              tintColor="#319aff"
              colors={['#319aff']}
            />
          }
          ListEmptyComponent={
            <View style={styles.empty}>
              <Text style={styles.emptyIcon}>{loading ? '⏳' : '🏕️'}</Text>
              <Text style={styles.emptyText}>
                {loading ? 'Loading relief centres…' : 'No relief centres found.'}
              </Text>
            </View>
          }
        />
      ) : (
        <MapView
          style={styles.map}
          provider={Platform.OS === 'android' ? PROVIDER_GOOGLE : undefined}
          initialRegion={DEFAULT_REGION}
          customMapStyle={darkMapStyle}
        >
          {centres.map(centre => (
            <Marker
              key={centre.id}
              coordinate={{ latitude: centre.latitude, longitude: centre.longitude }}
              title={centre.name}
              description={`${centre.district} · ${centre.operational_status} · ${centre.affected_population.toLocaleString()} people`}
              pinColor={PRIORITY_COLOR[centre.priority] ?? '#319aff'}
            />
          ))}
        </MapView>
      )}
    </View>
  );
}

const darkMapStyle = [
  { elementType: 'geometry', stylers: [{ color: '#0b1928' }] },
  { elementType: 'labels.text.fill', stylers: [{ color: '#a7b9cc' }] },
  { elementType: 'labels.text.stroke', stylers: [{ color: '#071321' }] },
  { featureType: 'road', elementType: 'geometry', stylers: [{ color: '#20364d' }] },
  { featureType: 'water', elementType: 'geometry', stylers: [{ color: '#1a3a5c' }] },
];

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#071321' },
  toggle: {
    flexDirection: 'row',
    backgroundColor: '#0b1928',
    margin: 12,
    borderRadius: 8,
    padding: 4,
    borderWidth: 1,
    borderColor: '#20364d',
  },
  toggleBtn: {
    flex: 1,
    paddingVertical: 8,
    alignItems: 'center',
    borderRadius: 6,
  },
  toggleActive: {
    backgroundColor: '#10243a',
  },
  toggleText: {
    color: '#6c8099',
    fontWeight: '600',
    fontSize: 14,
  },
  toggleTextActive: {
    color: '#319aff',
  },
  cacheNote: {
    color: '#6c8099',
    fontSize: 11,
    textAlign: 'center',
    marginBottom: 6,
  },
  list: {
    padding: 12,
    paddingBottom: 40,
  },
  map: {
    flex: 1,
  },
  empty: {
    paddingTop: 80,
    alignItems: 'center',
    gap: 12,
  },
  emptyIcon: { fontSize: 40 },
  emptyText: { color: '#a7b9cc', fontSize: 16 },
});
