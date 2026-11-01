import React, { useEffect, useState, useCallback } from 'react';
import {
  View,
  Text,
  StyleSheet,
  FlatList,
  TouchableOpacity,
  RefreshControl,
  Alert,
  ActivityIndicator,
} from 'react-native';
import { OfflineBanner } from '../../components/OfflineBanner';
import { listDispatchOrders, dispatchOrder, deliverOrder } from '../../api/dispatch';
import type { DispatchOrder } from '../../types';

const STATUS_COLOR: Record<string, string> = {
  draft: '#6c8099',
  awaiting_approval: '#ffd740',
  approved: '#319aff',
  dispatched: '#ff963d',
  in_transit: '#21c5c2',
  delayed: '#f15b5b',
  delivered: '#21b989',
  cancelled: '#f15b5b',
};

const SUPPLY_EMOJI: Record<string, string> = {
  food_kit: '🍱',
  water_litre: '💧',
  medical_kit: '🏥',
  hygiene_kit: '🧼',
};

function OrderCard({
  order,
  warehouseName,
  centreName,
  onAction,
  actionLoading,
}: {
  order: DispatchOrder;
  warehouseName: string;
  centreName: string;
  onAction: (order: DispatchOrder) => void;
  actionLoading: boolean;
}) {
  const canDispatch = order.status === 'approved';
  const canDeliver = order.status === 'dispatched' || order.status === 'in_transit';
  const showAction = canDispatch || canDeliver;

  return (
    <View style={styles.card}>
      <View style={styles.cardHeader}>
        <Text style={styles.orderCode}>{order.order_code}</Text>
        <View style={[styles.statusBadge, { backgroundColor: (STATUS_COLOR[order.status] ?? '#6c8099') + '22' }]}>
          <Text style={[styles.statusText, { color: STATUS_COLOR[order.status] ?? '#6c8099' }]}>
            {order.status.replace(/_/g, ' ').toUpperCase()}
          </Text>
        </View>
      </View>

      <Text style={styles.route}>
        📦 {warehouseName} → 🏕️ {centreName}
      </Text>

      <View style={styles.items}>
        {order.items.map(item => (
          <Text key={item.id} style={styles.item}>
            {SUPPLY_EMOJI[item.supply_type] ?? '📦'} {item.quantity.toLocaleString()} {item.unit} {item.supply_type.replace(/_/g, ' ')}
          </Text>
        ))}
      </View>

      <Text style={styles.weight}>
        ⚖️ {order.total_cargo_weight_kg.toFixed(0)} kg · ~{order.estimated_travel_time_minutes} min
      </Text>

      {order.progress_percent > 0 && order.progress_percent < 100 && (
        <View style={styles.progressBar}>
          <View style={[styles.progressFill, { width: `${order.progress_percent}%` }]} />
        </View>
      )}

      {showAction && (
        <TouchableOpacity
          style={[styles.actionBtn, canDeliver && styles.deliverBtn]}
          onPress={() => onAction(order)}
          disabled={actionLoading}
        >
          {actionLoading ? (
            <ActivityIndicator size="small" color="#fff" />
          ) : (
            <Text style={styles.actionBtnText}>
              {canDispatch ? '🚚 Mark as Dispatched' : '✅ Confirm Delivery'}
            </Text>
          )}
        </TouchableOpacity>
      )}
    </View>
  );
}

export default function TasksScreen() {
  const [orders, setOrders] = useState<DispatchOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [refreshing, setRefreshing] = useState(false);
  const [offline, setOffline] = useState(false);
  const [actionLoadingId, setActionLoadingId] = useState<number | null>(null);

  const fetchOrders = useCallback(async (isRefresh = false) => {
    if (isRefresh) setRefreshing(true);
    else setLoading(true);
    try {
      const res = await listDispatchOrders();
      setOrders(res.orders);
      setOffline(false);
    } catch {
      setOffline(true);
    } finally {
      setLoading(false);
      setRefreshing(false);
    }
  }, []);

  useEffect(() => { fetchOrders(); }, [fetchOrders]);

  const handleAction = useCallback(async (order: DispatchOrder) => {
    const canDispatch = order.status === 'approved';
    const canDeliver = order.status === 'dispatched' || order.status === 'in_transit';

    const actionLabel = canDispatch ? 'mark this order as dispatched' : 'confirm delivery of this order';

    Alert.alert(
      'Confirm action',
      `Are you sure you want to ${actionLabel}? (${order.order_code})`,
      [
        { text: 'Cancel', style: 'cancel' },
        {
          text: 'Confirm',
          onPress: async () => {
            setActionLoadingId(order.id);
            try {
              if (canDispatch) {
                const result = await dispatchOrder(order.id);
                setOrders(prev => prev.map(o => o.id === order.id ? result.order : o));
              } else if (canDeliver) {
                const result = await deliverOrder(order.id);
                setOrders(prev => prev.map(o => o.id === order.id ? result.order : o));
              }
              Alert.alert('✅ Updated', 'Order status updated. Web dashboard will reflect this change.');
            } catch (err: any) {
              Alert.alert('Error', err?.message ?? 'Failed to update order status.');
            } finally {
              setActionLoadingId(null);
            }
          },
        },
      ],
    );
  }, []);

  if (loading) {
    return (
      <View style={styles.center}>
        <ActivityIndicator size="large" color="#319aff" />
        <Text style={styles.loadingText}>Loading dispatch queue…</Text>
      </View>
    );
  }

  return (
    <View style={styles.root}>
      <OfflineBanner offline={offline} />
      <FlatList
        data={orders}
        keyExtractor={o => String(o.id)}
        contentContainerStyle={styles.list}
        renderItem={({ item }) => (
          <OrderCard
            order={item}
            warehouseName={`Warehouse #${item.warehouse_id}`}
            centreName={`Centre #${item.relief_centre_id}`}
            onAction={handleAction}
            actionLoading={actionLoadingId === item.id}
          />
        )}
        refreshControl={
          <RefreshControl
            refreshing={refreshing}
            onRefresh={() => fetchOrders(true)}
            tintColor="#319aff"
            colors={['#319aff']}
          />
        }
        ListHeaderComponent={
          <Text style={styles.heading}>📋 Dispatch Queue</Text>
        }
        ListEmptyComponent={
          <View style={styles.empty}>
            <Text style={styles.emptyIcon}>📭</Text>
            <Text style={styles.emptyText}>
              {offline ? 'No cached orders. Connect to refresh.' : 'No active dispatch orders.'}
            </Text>
          </View>
        }
      />
    </View>
  );
}

const styles = StyleSheet.create({
  root: { flex: 1, backgroundColor: '#071321' },
  center: { flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, backgroundColor: '#071321' },
  loadingText: { color: '#a7b9cc' },
  list: { padding: 14, paddingBottom: 40 },
  heading: {
    color: '#f1f5f9',
    fontSize: 22,
    fontWeight: '800',
    marginBottom: 14,
  },
  card: {
    backgroundColor: '#10243a',
    borderRadius: 10,
    padding: 14,
    marginBottom: 12,
    borderWidth: 1,
    borderColor: '#20364d',
    gap: 8,
  },
  cardHeader: {
    flexDirection: 'row',
    justifyContent: 'space-between',
    alignItems: 'center',
  },
  orderCode: {
    color: '#f1f5f9',
    fontWeight: '800',
    fontSize: 16,
    fontFamily: 'monospace',
  },
  statusBadge: {
    paddingHorizontal: 8,
    paddingVertical: 3,
    borderRadius: 6,
  },
  statusText: {
    fontSize: 11,
    fontWeight: '700',
    letterSpacing: 0.5,
  },
  route: {
    color: '#a7b9cc',
    fontSize: 13,
    lineHeight: 18,
  },
  items: { gap: 3 },
  item: {
    color: '#f1f5f9',
    fontSize: 13,
  },
  weight: {
    color: '#6c8099',
    fontSize: 12,
  },
  progressBar: {
    height: 4,
    backgroundColor: '#20364d',
    borderRadius: 2,
    overflow: 'hidden',
  },
  progressFill: {
    height: '100%',
    backgroundColor: '#21c5c2',
    borderRadius: 2,
  },
  actionBtn: {
    backgroundColor: '#1a4a7a',
    borderRadius: 8,
    paddingVertical: 12,
    alignItems: 'center',
    borderWidth: 1,
    borderColor: '#319aff',
    marginTop: 4,
  },
  deliverBtn: {
    backgroundColor: '#0d3a2e',
    borderColor: '#21b989',
  },
  actionBtnText: {
    color: '#f1f5f9',
    fontWeight: '700',
    fontSize: 14,
  },
  empty: {
    paddingTop: 80,
    alignItems: 'center',
    gap: 12,
  },
  emptyIcon: { fontSize: 40 },
  emptyText: { color: '#a7b9cc', fontSize: 16, textAlign: 'center' },
});
