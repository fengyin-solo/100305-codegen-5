<template>
  <div class="keeper-switch">
    <span class="keeper-label">当前保管员（决定授权）</span>
    <select :value="session.operatorId" @change="onChange">
      <option v-for="wh in session.warehouses" :key="wh.code" :value="wh.keeperId">
        {{ wh.keeperName }} · {{ wh.name }}
      </option>
    </select>
  </div>
</template>

<script setup lang="ts">
import { onMounted } from 'vue'

import { spareApi } from '@/api/spare'
import { useSpareSession } from '@/stores/spareSession'

const session = useSpareSession()

async function loadWarehouses() {
  if (session.warehouses.length) return
  const meta = await spareApi.meta()
  session.setWarehouses(
    meta.warehouses.map((wh) => ({
      code: wh.code,
      name: wh.name,
      keeperId: wh.keeper_id,
      keeperName: wh.keeper_name,
    })),
  )
}

function onChange(event: Event) {
  session.switchTo((event.target as HTMLSelectElement).value)
}

onMounted(loadWarehouses)
</script>
