#pragma once

#include "CoreMinimal.h"

struct FCapturedKeypoint
{
    float ImageX = 0.0f;
    float ImageY = 0.0f;
    int32 Visibility = 0;  // 0=not labeled, 1=labeled occluded, 2=visible
};

class UESYNTHCAPTURE_API FSynthCOCOExporter
{
public:
    FSynthCOCOExporter(const FString& InOutputPath, const FString& InDatasetName);
    ~FSynthCOCOExporter();

    void Begin();
    int32 AddImage(const FString& FileName, int32 Width, int32 Height, const TMap<FString, FString>& Metadata);
    int32 AddAnnotation(int32 ImageId, const FVector4& BBoxXYWH, const TArray<FCapturedKeypoint>& Keypoints, float Area);
    void End();

private:
    FString OutputPath;
    FString DatasetName;
    TArray<TSharedPtr<class FJsonObject>> Images;
    TArray<TSharedPtr<class FJsonObject>> Annotations;
    int32 NextImageId = 1;
    int32 NextAnnotationId = 1;
    bool bBegun = false;
};
