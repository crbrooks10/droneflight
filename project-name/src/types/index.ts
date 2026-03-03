export interface KMZFile {
    name: string;
    size: number;
    data: ArrayBuffer;
}

export interface KMZData {
    coordinates: number[][];
    altitude: number;
    description: string;
}

export interface EditingParameters {
    scale: number;
    rotation: { x: number; y: number; z: number };
    translation: { x: number; y: number; z: number };
}

export interface RenderingOptions {
    backgroundColor: string;
    wireframe: boolean;
    lighting: boolean;
}