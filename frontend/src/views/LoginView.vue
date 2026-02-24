<script setup>
import LoginModal from '../components/LoginModal.vue';
import { useRouter, useRoute } from 'vue-router';

const router = useRouter();
const route = useRoute();

const handleClose = () => {
  // If there is a redirect query, go there, otherwise go home
  const redirect = route.query.redirect || '/';
  router.push(redirect);
};
</script>

<template>
  <div class="login-page">
    <!-- Reuse the Login Modal, force it open -->
    <!-- We hide the close button via CSS or just handle close event -> go home -->
    <LoginModal :isOpen="true" @close="handleClose" />
  </div>
</template>

<style scoped>
.login-page {
  min-height: 100vh;
  background-color: var(--color-background);
  /* Optional: Add a nice background image or pattern here */
}

/* Optional: Override modal style if needed via deep selector to hide close button if we want to force login */
/* 
:deep(.close-btn) {
    display: none; 
} 
*/
</style>
