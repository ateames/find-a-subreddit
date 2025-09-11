# Environment Configuration Guide

## Overview

This guide explains how to configure environment variables for production deployment on DigitalOcean App Platform.

## Required Environment Variables

### 1. **REDDIT_REDIRECT_URI** ⚠️ REQUIRED
**Purpose**: The OAuth callback URL that Reddit will redirect to after authentication.

**Production Value**:
```
REDDIT_REDIRECT_URI=https://api.YOUR_DOMAIN/api/auth/reddit/callback
```

**Development Value**:
```
REDDIT_REDIRECT_URI=http://localhost:8001/api/auth/reddit/callback
```

**Why Required**: This must exactly match what you configure in your Reddit App settings. For production, it must be your actual API domain.

### 2. **FRONTEND_ORIGIN** ⚠️ REQUIRED
**Purpose**: The frontend URL for CORS and post-login redirects.

**Production Value**:
```
FRONTEND_ORIGIN=https://YOUR_DOMAIN
```

**Development Value**:
```
FRONTEND_ORIGIN=http://localhost:5173
```

**Why Required**: Used for CORS configuration and redirecting users after OAuth login.

### 3. **FRONTEND_DOMAIN** ⚠️ REQUIRED
**Purpose**: Used by the Reddit posting API for CORS configuration.

**Production Value**:
```
FRONTEND_DOMAIN=https://YOUR_DOMAIN
```

**Development Value**:
```
FRONTEND_DOMAIN=http://localhost:5173
```

**Why Required**: Ensures the frontend can make authenticated requests to the Reddit posting endpoints.

## DigitalOcean App Platform Configuration

### 1. **Backend Service Environment Variables**

In your `.do/app.yaml`, ensure these are set:

```yaml
services:
  - name: backend
    # ... other config ...
    envs:
      # --- Required for Production ---
      - key: REDDIT_REDIRECT_URI
        scope: RUN_AND_BUILD_TIME
        value: "https://api.YOUR_DOMAIN/api/auth/reddit/callback"
      
      - key: FRONTEND_ORIGIN
        scope: RUN_AND_BUILD_TIME
        value: "https://YOUR_DOMAIN"
      
      - key: FRONTEND_DOMAIN
        scope: RUN_AND_BUILD_TIME
        value: "https://YOUR_DOMAIN"
      
      # --- Other required variables ---
      - key: DATABASE_URL
        scope: RUN_AND_BUILD_TIME
        type: SECRET
      
      - key: OPENAI_API_KEY
        scope: RUN_AND_BUILD_TIME
        type: SECRET
      
      - key: REDDIT_CLIENT_ID
        scope: RUN_AND_BUILD_TIME
        type: SECRET
      
      - key: REDDIT_CLIENT_SECRET
        scope: RUN_AND_BUILD_TIME
        type: SECRET
      
      - key: JWT_SECRET
        scope: RUN_AND_BUILD_TIME
        type: SECRET
```

### 2. **Frontend Service Environment Variables**

```yaml
services:
  - name: frontend
    # ... other config ...
    envs:
      - key: VITE_API_ORIGIN
        scope: RUN_AND_BUILD_TIME
        value: "https://api.YOUR_DOMAIN"
```

## Reddit App Configuration

### 1. **Redirect URI**
In your Reddit App settings (https://www.reddit.com/prefs/apps), set the redirect URI to:
```
https://api.YOUR_DOMAIN/api/auth/reddit/callback
```

### 2. **App Type**
Ensure your Reddit app is configured as a **web app** (not script or installed).

## Testing the Configuration

### 1. **Health Check**
After deployment, the `/health` endpoint should return:
```json
{
  "status": "ok",
  "database": "connected",
  "openai": "available"
}
```

### 2. **OAuth Flow**
1. Click "Log in with Reddit" on your frontend
2. Should redirect to Reddit OAuth
3. After authorization, should redirect back to your frontend
4. User should be logged in

### 3. **Common Issues**

**Error**: "REDDIT_REDIRECT_URI environment variable must be set"
- **Solution**: Ensure `REDDIT_REDIRECT_URI` is set in DigitalOcean

**Error**: "FRONTEND_ORIGIN environment variable must be set"
- **Solution**: Ensure `FRONTEND_ORIGIN` is set in DigitalOcean

**OAuth Error**: "redirect_uri_mismatch"
- **Solution**: Check that Reddit App redirect URI matches `REDDIT_REDIRECT_URI`

**CORS Error**: "Origin not allowed"
- **Solution**: Ensure `FRONTEND_ORIGIN` matches your actual frontend domain

## Development vs Production

### Development
```bash
# .env file
REDDIT_REDIRECT_URI=http://localhost:8001/api/auth/reddit/callback
FRONTEND_ORIGIN=http://localhost:5173
FRONTEND_DOMAIN=http://localhost:5173
```

### Production (DigitalOcean)
```bash
# Environment variables
REDDIT_REDIRECT_URI=https://api.YOUR_DOMAIN/api/auth/reddit/callback
FRONTEND_ORIGIN=https://YOUR_DOMAIN
FRONTEND_DOMAIN=https://YOUR_DOMAIN
```

## Security Notes

1. **HTTPS Required**: Production URLs must use HTTPS
2. **Domain Validation**: Ensure domains match your actual deployment
3. **Secret Management**: Use DigitalOcean secrets for sensitive values
4. **CORS**: Only allow your actual frontend domain
