#include "SynthCaptureSubsystem.h"
#include "SynthVehicleAnnotator.h"
#include "SynthCOCOExporter.h"
#include "Camera/CameraComponent.h"
#include "Camera/PlayerCameraManager.h"
#include "GameFramework/PlayerController.h"

DEFINE_LOG_CATEGORY_STATIC(LogSynthCapture, Log, All);

// Constructor and destructor are defined here (not defaulted in the header) so the
// TUniquePtr<FSynthCOCOExporter> member is destroyed in a translation unit where
// FSynthCOCOExporter is a complete type. SynthCOCOExporter.h is included above.
USynthCaptureSubsystem::USynthCaptureSubsystem() = default;
USynthCaptureSubsystem::~USynthCaptureSubsystem() = default;
USynthCaptureSubsystem::USynthCaptureSubsystem(FVTableHelper& Helper) : Super(Helper) {}

void USynthCaptureSubsystem::BeginCaptureSession(const FCaptureSessionConfig& Config)
{
    if (bSessionActive)
    {
        UE_LOG(LogSynthCapture, Warning, TEXT("BeginCaptureSession called while session active. Ending previous."));
        EndCaptureSession();
    }
    ActiveConfig = Config;
    bSessionActive = true;
    NextImageId = 1;
    NextAnnotationId = 1;

    const FString OutPath = FPaths::Combine(ActiveConfig.OutputDirectory, TEXT("annotations"), TEXT("coco.json"));
    Exporter = MakeUnique<FSynthCOCOExporter>(OutPath, ActiveConfig.DatasetName);
    Exporter->Begin();

    UE_LOG(LogSynthCapture, Log, TEXT("Capture session '%s' started, output=%s"),
        *ActiveConfig.SessionId, *ActiveConfig.OutputDirectory);
}

void USynthCaptureSubsystem::EndCaptureSession()
{
    if (!bSessionActive)
    {
        return;
    }
    if (Exporter.IsValid())
    {
        Exporter->End();
        Exporter.Reset();
    }
    bSessionActive = false;
    UE_LOG(LogSynthCapture, Log, TEXT("Capture session ended."));
}

void USynthCaptureSubsystem::CaptureFrame(int32 FrameId)
{
    if (!bSessionActive)
    {
        UE_LOG(LogSynthCapture, Error, TEXT("CaptureFrame called without active session."));
        return;
    }
    if (!Exporter.IsValid())
    {
        return;
    }

    // Phase 0: assume a single PlayerCameraManager-driven camera. RGB write happens
    // via a SceneCaptureComponent2D owned by BP_SceneController; this routine only
    // writes the keypoint annotations.
    UWorld* W = GetWorld();
    if (!W) return;

    APlayerCameraManager* PCM = W->GetFirstPlayerController() ? W->GetFirstPlayerController()->PlayerCameraManager : nullptr;
    UCameraComponent* Cam = PCM ? PCM->ViewTarget.Target->FindComponentByClass<UCameraComponent>() : nullptr;
    if (!Cam)
    {
        UE_LOG(LogSynthCapture, Warning, TEXT("CaptureFrame: no active CameraComponent found."));
        return;
    }

    const FString FileName = FString::Printf(TEXT("rgb/frame_%06d_cam0.png"), FrameId);
    TMap<FString, FString> Meta;
    Meta.Add(TEXT("frame_id"), FString::FromInt(FrameId));
    Meta.Add(TEXT("camera_id"), TEXT("0"));
    const int32 ImageId = Exporter->AddImage(FileName, ActiveConfig.ImageWidth, ActiveConfig.ImageHeight, Meta);

    for (TWeakObjectPtr<USynthVehicleAnnotator>& Weak : Annotators)
    {
        USynthVehicleAnnotator* Ann = Weak.Get();
        if (!Ann) continue;

        TArray<FCapturedKeypoint> Kpts = Ann->CapturePoints(Cam, ActiveConfig.ImageWidth, ActiveConfig.ImageHeight);

        // Compute bbox from visible keypoints (Phase 0 fallback; better bbox in Phase 1).
        float MinX = TNumericLimits<float>::Max(), MinY = TNumericLimits<float>::Max();
        float MaxX = TNumericLimits<float>::Lowest(), MaxY = TNumericLimits<float>::Lowest();
        bool bAny = false;
        for (const FCapturedKeypoint& K : Kpts)
        {
            if (K.Visibility > 0)
            {
                MinX = FMath::Min(MinX, K.ImageX);
                MinY = FMath::Min(MinY, K.ImageY);
                MaxX = FMath::Max(MaxX, K.ImageX);
                MaxY = FMath::Max(MaxY, K.ImageY);
                bAny = true;
            }
        }
        if (!bAny) continue;

        const FVector4 BBox(MinX, MinY, MaxX - MinX, MaxY - MinY);
        const float Area = (MaxX - MinX) * (MaxY - MinY);
        Exporter->AddAnnotation(ImageId, BBox, Kpts, Area);
    }
}

void USynthCaptureSubsystem::RegisterAnnotator(USynthVehicleAnnotator* Annotator)
{
    if (Annotator)
    {
        Annotators.AddUnique(Annotator);
    }
}

void USynthCaptureSubsystem::UnregisterAnnotator(USynthVehicleAnnotator* Annotator)
{
    Annotators.RemoveAll([Annotator](const TWeakObjectPtr<USynthVehicleAnnotator>& W)
    {
        return W.Get() == Annotator;
    });
}
