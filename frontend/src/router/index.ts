import { createRouter, createWebHistory } from 'vue-router'

import Dashboard from '@/views/Dashboard.vue'
const Site = () => import('@/views/site/index.vue')
const Tower = () => import('@/views/tower/index.vue')
const Power = () => import('@/views/power/index.vue')
const Battery = () => import('@/views/battery/index.vue')
const Genset = () => import('@/views/genset/index.vue')
const Rectifier = () => import('@/views/rectifier/index.vue')
const Ac = () => import('@/views/ac/index.vue')
const Antenna = () => import('@/views/antenna/index.vue')
const Transmission = () => import('@/views/transmission/index.vue')
const Feeder = () => import('@/views/feeder/index.vue')
const Lightningprot = () => import('@/views/lightningprot/index.vue')
const Firealarm = () => import('@/views/firealarm/index.vue')
const Dooraccess = () => import('@/views/dooraccess/index.vue')
const Patrol = () => import('@/views/patrol/index.vue')
const Fuel = () => import('@/views/fuel/index.vue')
const Rental = () => import('@/views/rental/index.vue')
const Electricbill = () => import('@/views/electricbill/index.vue')
const Demolition = () => import('@/views/demolition/index.vue')
const Emergency = () => import('@/views/emergency/index.vue')
const Energyeff = () => import('@/views/energyeff/index.vue')
const Sparepart = () => import('@/views/sparepart/index.vue')

const router = createRouter({
  history: createWebHistory(),
  routes: [
    { path: '/', name: 'dashboard', component: Dashboard },
    { path: '/site', name: 'site', component: Site },
    { path: '/tower', name: 'tower', component: Tower },
    { path: '/power', name: 'power', component: Power },
    { path: '/battery', name: 'battery', component: Battery },
    { path: '/genset', name: 'genset', component: Genset },
    { path: '/rectifier', name: 'rectifier', component: Rectifier },
    { path: '/ac', name: 'ac', component: Ac },
    { path: '/antenna', name: 'antenna', component: Antenna },
    { path: '/transmission', name: 'transmission', component: Transmission },
    { path: '/feeder', name: 'feeder', component: Feeder },
    { path: '/lightningprot', name: 'lightningprot', component: Lightningprot },
    { path: '/firealarm', name: 'firealarm', component: Firealarm },
    { path: '/dooraccess', name: 'dooraccess', component: Dooraccess },
    { path: '/patrol', name: 'patrol', component: Patrol },
    { path: '/fuel', name: 'fuel', component: Fuel },
    { path: '/rental', name: 'rental', component: Rental },
    { path: '/electricbill', name: 'electricbill', component: Electricbill },
    { path: '/demolition', name: 'demolition', component: Demolition },
    { path: '/emergency', name: 'emergency', component: Emergency },
    { path: '/energyeff', name: 'energyeff', component: Energyeff },
    { path: '/sparepart', name: 'sparepart', component: Sparepart },
  ],
})

export default router
