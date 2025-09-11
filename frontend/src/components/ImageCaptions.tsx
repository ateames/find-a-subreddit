// ROOT/src/components/ImageCaptions.tsx
import React from "react";

interface ImageCaptionsProps {
  imageCaptions: string[];
}

const ImageCaptions: React.FC<ImageCaptionsProps> = ({ imageCaptions }) => {
  if (!imageCaptions || imageCaptions.length === 0) return null;
  return (
    <div className="mb-6 p-4 rounded-xl bg-gray-50 border border-gray-200">
      <div className="font-semibold mb-2 text-gray-700">Image Analysis Used in Search</div>
      <ul className="list-disc pl-6 space-y-2 text-gray-800">
        {imageCaptions.map((caption, idx) => (
          <li key={idx} className="whitespace-pre-line">{caption}</li>
        ))}
      </ul>
    </div>
  );
};

export default ImageCaptions;
