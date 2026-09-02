<script setup lang="ts">
interface ShopTag {
  name?: string
}

interface ShopItem {
  platformStoreName?: string
  principalUserName?: string
  platformStoreId?: string | number
  logoUrl?: string
  platformType?: string
  tagList?: (ShopTag | string)[]
  address?: string
}

defineProps<{ shops?: ShopItem[] }>()

function tagName(tag: ShopTag | string): string {
  return typeof tag === 'string' ? tag : tag.name || ''
}
</script>

<template>
  <div class="shop-list">
    <div
      v-for="shop in shops"
      :key="String(shop.platformStoreId ?? shop.platformStoreName ?? '')"
      class="shop-card"
    >
      <img v-if="shop.logoUrl" class="logo" :src="shop.logoUrl" alt="" />
      <div class="main">
        <div class="name-row">
          <span class="name">{{ shop.platformStoreName || '未命名店铺' }}</span>
          <span v-if="shop.platformType" class="platform">{{ shop.platformType }}</span>
        </div>
        <div v-if="shop.principalUserName" class="owner">
          负责人：{{ shop.principalUserName }}
        </div>
        <div v-if="shop.platformStoreId" class="store-id">
          店铺 ID：{{ shop.platformStoreId }}
        </div>
        <div v-if="shop.tagList?.length" class="tags">
          <span v-for="tag in shop.tagList" :key="tagName(tag)" class="tag">
            {{ tagName(tag) }}
          </span>
        </div>
      </div>
    </div>
    <p v-if="!shops?.length" class="empty">暂无店铺信息</p>
  </div>
</template>

<style>
.shop-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.shop-card {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  padding: 12px 14px;
  background: #fff;
  border-radius: 12px;
  box-shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
}

.logo {
  width: 44px;
  height: 44px;
  border-radius: 50%;
  object-fit: cover;
  background: #f2f4f7;
  flex-shrink: 0;
}

.main {
  min-width: 0;
  flex: 1;
}

.name-row {
  display: flex;
  align-items: center;
  gap: 6px;
}

.name {
  font-size: 15px;
  font-weight: 600;
  line-height: 1.4;
  color: #1f2329;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.platform {
  padding: 1px 6px;
  border-radius: 4px;
  background: #f2f4f7;
  font-size: 12px;
  color: #646a73;
  flex-shrink: 0;
}

.owner,
.store-id {
  margin-top: 3px;
  font-size: 12px;
  color: #8a919f;
}

.tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-top: 8px;
}

.tag {
  padding: 2px 8px;
  border-radius: 999px;
  background: #eef4ff;
  font-size: 12px;
  color: #3b6cf0;
}

.empty {
  padding: 24px 0;
  text-align: center;
  font-size: 13px;
  color: #8a919f;
}

@media (max-width: 360px) {
  .logo {
    width: 36px;
    height: 36px;
  }
}
</style>
