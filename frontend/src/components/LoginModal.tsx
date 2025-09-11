// src/components/LoginModal.tsx
import React from "react";

interface LoginModalProps {
  open: boolean;
  onClose: () => void;
  onLoginClick: () => void;
}

const LoginModal: React.FC<LoginModalProps> = ({ open, onClose, onLoginClick }) => {
  if (!open) return null;

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black bg-opacity-40">
      <div className="bg-white rounded-lg shadow-lg max-w-xs w-full p-6 text-center">
        <h2 className="text-xl font-bold mb-3">Reddit Login Required</h2>
        <p className="mb-5 text-gray-600">
          You need to log in with Reddit to post to a subreddit.
        </p>
        <button
          className="w-full bg-orange-500 hover:bg-orange-600 text-white py-2 rounded-lg mb-3 font-bold"
          onClick={onLoginClick}
        >
          Log in with Reddit
        </button>
        <button
          className="w-full bg-gray-200 hover:bg-gray-300 text-gray-700 py-2 rounded-lg"
          onClick={onClose}
        >
          Cancel
        </button>
      </div>
    </div>
  );
};

export default LoginModal;
