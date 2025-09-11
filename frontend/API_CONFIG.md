# API Configuration

## Overview

The frontend now uses a centralized API helper (`src/lib/api.ts`) that automatically handles API calls to the correct backend URL based on the environment.

## Environment Variables

### VITE_API_ORIGIN

Set this environment variable to configure the API base URL:

- **Production**: `VITE_API_ORIGIN=https://api.YOUR_DOMAIN`
- **Development**: `VITE_API_ORIGIN=http://localhost:8001` (or leave unset for default)

## Usage

### In Components

Instead of hardcoded fetch calls like:
```typescript
// ❌ Old way
const res = await fetch("http://localhost:8001/analyze_post", {
  method: "POST",
  body: formData,
  credentials: "include",
});
```

Use the API helper:
```typescript
// ✅ New way
import { apiFetch } from "../lib/api";

const res = await apiFetch("/api/analyze_post", {
  method: "POST",
  body: formData,
});
```

### Benefits

1. **Environment-aware**: Automatically uses the correct API URL
2. **Credentials included**: Automatically includes `credentials: "include"` for auth
3. **Centralized**: Easy to update API configuration in one place
4. **Type-safe**: Proper TypeScript support

## Migration

All components have been updated to use the new API helper. The following files were updated:

- `src/RedditAnalyzer.tsx`
- `src/App.tsx`
- `src/components/SubredditCard.tsx`
- `src/components/LeftMenu.tsx`

## Development vs Production

- **Development**: Uses `http://localhost:8001` as fallback
- **Production**: Uses `https://api.YOUR_DOMAIN` as fallback
- **Custom**: Set `VITE_API_ORIGIN` to override both
