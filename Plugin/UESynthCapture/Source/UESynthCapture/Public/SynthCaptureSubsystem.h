#pragma once

#include "CoreMinimal.h"
#include "Subsystems/WorldSubsystem.h"
#include "SynthCaptureSubsystem.generated.h"

class USynthVehicleAnnotator;

USTRUCT(BlueprintType)
struct FCaptureSessionConfig
{
    GENERATED_BODY()

    UPROPERTY(EditAnywhere, BlueprintReadWrite)
    FString SessionId;

    UPROPERTY(EditAnywhere, BlueprintReadWrite)
    FString OutputDirectory;

    UPROPERTY(EditAnywhere, BlueprintReadWrite)
    int32 ImageWidth = 1280;

    UPROPERTY(EditAnywhere, BlueprintReadWrite)
    int32 ImageHeight = 720;

    UPROPERTY(EditAnywhere, BlueprintReadWrite)
    FString DatasetName = TEXT("phase0-slice");
};

UCLASS()
class UESYNTHCAPTURE_API USynthCaptureSubsystem : public UWorldSubsystem
{
    GENERATED_BODY()

public:
    USynthCaptureSubsystem();
    virtual ~USynthCaptureSubsystem();

    // Declared here (and defined in the .cpp) so UHT does not auto-generate the
    // hot-reload vtable-helper constructor inline in the .gen.cpp, where the
    // forward-declared FSynthCOCOExporter held by TUniquePtr is still incomplete.
    USynthCaptureSubsystem(FVTableHelper& Helper);

    UFUNCTION(BlueprintCallable, Category = "UESynth")
    void BeginCaptureSession(const FCaptureSessionConfig& Config);

    UFUNCTION(BlueprintCallable, Category = "UESynth")
    void EndCaptureSession();

    UFUNCTION(BlueprintCallable, Category = "UESynth")
    void CaptureFrame(int32 FrameId);

    UFUNCTION(BlueprintCallable, Category = "UESynth")
    void RegisterAnnotator(USynthVehicleAnnotator* Annotator);

    UFUNCTION(BlueprintCallable, Category = "UESynth")
    void UnregisterAnnotator(USynthVehicleAnnotator* Annotator);

private:
    FCaptureSessionConfig ActiveConfig;
    bool bSessionActive = false;
    TArray<TWeakObjectPtr<USynthVehicleAnnotator>> Annotators;
    int32 NextImageId = 1;
    int32 NextAnnotationId = 1;

    // Owned writer to coco.json — minimal struct, not a UObject
    TUniquePtr<class FSynthCOCOExporter> Exporter;
};
