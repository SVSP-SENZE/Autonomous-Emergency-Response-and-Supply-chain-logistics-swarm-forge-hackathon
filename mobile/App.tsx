import React, { useState, useEffect } from 'react';
import {
  View,
  Text,
  StyleSheet,
  TouchableOpacity,
  SafeAreaView,
  ActivityIndicator,
} from 'react-native';
import { StatusBar } from 'expo-status-bar';
import { NavigationContainer } from '@react-navigation/native';
import { createBottomTabNavigator } from '@react-navigation/bottom-tabs';

// Screens
import SosScreen from './src/screens/citizen/SosScreen';
import SafeCampsScreen from './src/screens/citizen/SafeCampsScreen';
import TasksScreen from './src/screens/volunteer/TasksScreen';
import ReportHazardScreen from './src/screens/volunteer/ReportHazardScreen';

// Utils
import { loadRole, saveRole } from './src/utils/storage';
import type { AppRole } from './src/types';

const Tab = createBottomTabNavigator();

function CitizenTabs() {
  return (
    <Tab.Navigator
      screenOptions={{
        headerStyle: { backgroundColor: '#0b1928', borderBottomColor: '#20364d', borderBottomWidth: 1 },
        headerTintColor: '#f1f5f9',
        headerTitleStyle: { fontWeight: '700' },
        tabBarStyle: { backgroundColor: '#0b1928', borderTopColor: '#20364d', borderTopWidth: 1 },
        tabBarActiveTintColor: '#f15b5b',
        tabBarInactiveTintColor: '#6c8099',
      }}
    >
      <Tab.Screen
        name="SOS"
        component={SosScreen}
        options={{
          title: '🆘 Emergency SOS',
          tabBarLabel: 'SOS',
          tabBarIcon: ({ color }) => <Text style={{ fontSize: 20, color }}>🆘</Text>,
        }}
      />
      <Tab.Screen
        name="SafeCamps"
        component={SafeCampsScreen}
        options={{
          title: '🏕️ Safe Havens',
          tabBarLabel: 'Safe Havens',
          tabBarIcon: ({ color }) => <Text style={{ fontSize: 20, color }}>🏕️</Text>,
        }}
      />
    </Tab.Navigator>
  );
}

function VolunteerTabs() {
  return (
    <Tab.Navigator
      screenOptions={{
        headerStyle: { backgroundColor: '#0b1928', borderBottomColor: '#20364d', borderBottomWidth: 1 },
        headerTintColor: '#f1f5f9',
        headerTitleStyle: { fontWeight: '700' },
        tabBarStyle: { backgroundColor: '#0b1928', borderTopColor: '#20364d', borderTopWidth: 1 },
        tabBarActiveTintColor: '#319aff',
        tabBarInactiveTintColor: '#6c8099',
      }}
    >
      <Tab.Screen
        name="Tasks"
        component={TasksScreen}
        options={{
          title: '📋 Dispatch Queue',
          tabBarLabel: 'Tasks',
          tabBarIcon: ({ color }) => <Text style={{ fontSize: 20, color }}>📋</Text>,
        }}
      />
      <Tab.Screen
        name="ReportHazard"
        component={ReportHazardScreen}
        options={{
          title: '⚠️ Report Hazard',
          tabBarLabel: 'Report Hazard',
          tabBarIcon: ({ color }) => <Text style={{ fontSize: 20, color }}>⚠️</Text>,
        }}
      />
    </Tab.Navigator>
  );
}

function RolePicker({ onSelect }: { onSelect: (role: AppRole) => void }) {
  return (
    <SafeAreaView style={picker.root}>
      <StatusBar style="light" />
      <View style={picker.container}>
        <Text style={picker.logo}>⚡</Text>
        <Text style={picker.title}>ReliefMesh</Text>
        <Text style={picker.subtitle}>Field Companion</Text>
        <Text style={picker.tagline}>Tamil Nadu Flood Response</Text>

        <View style={picker.divider} />

        <Text style={picker.prompt}>I am a…</Text>

        <TouchableOpacity
          style={[picker.card, picker.citizenCard]}
          onPress={() => onSelect('citizen')}
          activeOpacity={0.8}
        >
          <Text style={picker.cardEmoji}>🏠</Text>
          <Text style={picker.cardTitle}>Citizen / Victim</Text>
          <Text style={picker.cardDesc}>
            I need help · Send emergency SOS · Find safe relief camps near me
          </Text>
        </TouchableOpacity>

        <TouchableOpacity
          style={[picker.card, picker.volunteerCard]}
          onPress={() => onSelect('volunteer')}
          activeOpacity={0.8}
        >
          <Text style={picker.cardEmoji}>🦺</Text>
          <Text style={picker.cardTitle}>Volunteer / Responder</Text>
          <Text style={picker.cardDesc}>
            I'm helping · Manage supply deliveries · Report field hazards
          </Text>
        </TouchableOpacity>

        <Text style={picker.footer}>
          Powered by ReliefMesh · Autonomous Disaster Response Platform
        </Text>
      </View>
    </SafeAreaView>
  );
}

export default function App() {
  const [role, setRole] = useState<AppRole | null>(null);
  const [initialising, setInitialising] = useState(true);

  useEffect(() => {
    loadRole().then(saved => {
      if (saved === 'citizen' || saved === 'volunteer') {
        setRole(saved);
      }
      setInitialising(false);
    });
  }, []);

  const handleSelectRole = (selected: AppRole) => {
    setRole(selected);
    saveRole(selected);
  };

  const handleSwitchRole = () => {
    setRole(null);
    saveRole('');
  };

  if (initialising) {
    return (
      <View style={{ flex: 1, backgroundColor: '#071321', alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator size="large" color="#319aff" />
      </View>
    );
  }

  if (!role) {
    return <RolePicker onSelect={handleSelectRole} />;
  }

  return (
    <NavigationContainer>
      <StatusBar style="light" />
      <View style={{ flex: 1 }}>
        {role === 'citizen' ? <CitizenTabs /> : <VolunteerTabs />}
        {/* Switch role button */}
        <TouchableOpacity style={switchBtn.btn} onPress={handleSwitchRole}>
          <Text style={switchBtn.text}>Switch role</Text>
        </TouchableOpacity>
      </View>
    </NavigationContainer>
  );
}

const picker = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#071321' },
  container: {
    flex: 1,
    alignItems: 'center',
    justifyContent: 'center',
    padding: 28,
  },
  logo: { fontSize: 56, marginBottom: 8 },
  title: {
    color: '#f1f5f9',
    fontSize: 32,
    fontWeight: '900',
    letterSpacing: 1,
  },
  subtitle: {
    color: '#319aff',
    fontSize: 16,
    fontWeight: '600',
    marginTop: 2,
  },
  tagline: {
    color: '#6c8099',
    fontSize: 13,
    marginTop: 4,
  },
  divider: {
    width: 60,
    height: 2,
    backgroundColor: '#20364d',
    borderRadius: 1,
    marginVertical: 28,
  },
  prompt: {
    color: '#a7b9cc',
    fontSize: 15,
    marginBottom: 16,
    fontWeight: '600',
  },
  card: {
    width: '100%',
    borderRadius: 14,
    padding: 20,
    marginBottom: 14,
    borderWidth: 1,
    alignItems: 'center',
    gap: 8,
  },
  citizenCard: {
    backgroundColor: '#1a0a0a',
    borderColor: '#f15b5b',
  },
  volunteerCard: {
    backgroundColor: '#0a1428',
    borderColor: '#319aff',
  },
  cardEmoji: { fontSize: 40 },
  cardTitle: {
    color: '#f1f5f9',
    fontSize: 18,
    fontWeight: '800',
  },
  cardDesc: {
    color: '#a7b9cc',
    fontSize: 13,
    textAlign: 'center',
    lineHeight: 18,
  },
  footer: {
    color: '#6c8099',
    fontSize: 11,
    marginTop: 28,
    textAlign: 'center',
  },
});

const switchBtn = StyleSheet.create({
  btn: {
    position: 'absolute',
    bottom: 90,
    alignSelf: 'center',
    backgroundColor: 'rgba(16,36,58,0.9)',
    borderRadius: 20,
    paddingHorizontal: 16,
    paddingVertical: 6,
    borderWidth: 1,
    borderColor: '#20364d',
  },
  text: {
    color: '#6c8099',
    fontSize: 12,
    fontWeight: '600',
  },
});
